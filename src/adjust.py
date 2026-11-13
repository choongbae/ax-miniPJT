"""지난주 판정 결과(하향/유지/상향)를 다음 계획에 반영하는 규칙.

- 하향: 같은 종류(슛 / 슛 외)에서 더 쉬운 연습 메뉴로 바꾼다. (슛은 거리 축소·제자리슛 쪽)
- 상향: 같은 종류에서 더 어려운 연습 메뉴로 바꾼다. (슛은 무빙슛·캐치앤슛·거리 확대 쪽)
- 유지: 그대로 둔다. 기록이 없던 연습 메뉴(carry_over)는 다음 주 계획에 다시 넣는다.
이미 가장 쉽거나 어려워서(또는 장비가 없어서) 바꿀 메뉴가 없으면 바꾸라고 요구하지 않는다.
올릴 곳이 없는 상향은 그 메뉴를 계획에 유지하게 하고, 다른 분야 추천은 src/recommend.py가 규칙으로 따로 한다.
"""
from src.models import Drill, UserInput, WeeklyPlan
from src.tools import DrillJudgment, Verdict

_ORDER = {"초급": 0, "중급": 1, "상급": 2}


def adjustment_candidates(
    drill: Drill, verdict: Verdict, catalog: list[Drill], user: UserInput
) -> list[Drill]:
    """하향이면 더 쉬운, 상향이면 더 어려운 같은 종류의 연습 메뉴 중 사용자가 할 수 있는 것."""
    if verdict == "유지":
        return []
    step = -1 if verdict == "하향" else 1
    owned = set(user.equipment)
    return [
        c
        for c in catalog
        if c.is_shooting == drill.is_shooting
        and set(c.requires) <= owned
        and (_ORDER[c.difficulty] - _ORDER[drill.difficulty]) * step > 0
    ]


def floor_notices(judgments: list[DrillJudgment] | None, catalog: list[Drill], user: UserInput) -> list[str]:
    """하향 판정인데 더 쉬운 메뉴가 없을 때(가장 쉬운 초급이거나 장비로 할 수 있는 쉬운 메뉴가 없음) 사용자에게 보일 안내.

    판정은 그대로 두고, 이번 주도 같은 메뉴를 하되 세트·횟수를 줄이라고 규칙으로 안내한다 (모델 아님).
    """
    by_name = {d.name: d for d in catalog}
    out: list[str] = []
    for j in judgments or []:
        drill = by_name.get(j.drill)
        if drill is None or j.carry_over or j.verdict != "하향" or adjustment_candidates(drill, "하향", catalog, user):
            continue
        why = "이미 가장 쉬운 난이도(초급)라" if drill.difficulty == "초급" else "지금 가진 장소·장비로 할 수 있는 더 쉬운 메뉴가 없어"
        out.append(f"'{drill.name}'은(는) {why} 낮출 곳이 없어요. 이번 주도 같은 메뉴를 하되 세트나 횟수를 줄여서 해 보세요.")
    return out


def format_judgments(
    judgments: list[DrillJudgment] | None, catalog: list[Drill], user: UserInput
) -> str:
    """판정 결과를 계획 생성 프롬프트에 넣을 문장으로 만든다. 판정이 없으면 빈 문자열."""
    if not judgments:
        return ""
    by_name = {d.name: d for d in catalog}
    lines: list[str] = []
    for j in judgments:
        drill = by_name.get(j.drill)
        if j.carry_over:
            lines.append(
                f"- '{j.drill}': 지난주 기록이 없었습니다. 난이도를 바꾸지 말고 이번 주 계획에 같은 연습 메뉴를 다시 넣으세요."
            )
        elif j.verdict == "유지":
            lines.append(f"- '{j.drill}': 유지 ({j.reason}). 같은 난이도로 두세요.")
        else:
            candidates = adjustment_candidates(drill, j.verdict, catalog, user) if drill else []
            if candidates:
                how = (
                    "더 쉬운 연습 메뉴(슛이면 거리를 줄이거나 제자리슛 쪽)"
                    if j.verdict == "하향"
                    else "더 어려운 연습 메뉴(슛이면 무빙슛·캐치앤슛·거리 확대 쪽)"
                )
                lines.append(
                    f"- '{j.drill}': {j.verdict} ({j.reason}). 이 연습 메뉴는 빼고 {how}로 바꾸세요. "
                    f"후보: {', '.join(c.name for c in candidates)}"
                )
            elif j.verdict == "상향":  # 올라갈 메뉴가 없다: 유지한다. 다른 분야 추천은 서비스가 따로 안내한다 (src/recommend.py)
                lines.append(
                    f"- '{j.drill}': 상향 ({j.reason}). 더 어려운 연습 메뉴가 없으니 이 메뉴를 바꾸지 말고 이번 주 계획에 그대로 유지해서 넣으세요."
                )
            else:
                lines.append(
                    f"- '{j.drill}': {j.verdict} ({j.reason}). 바꿀 수 있는 연습 메뉴가 더 없으니 이 메뉴를 그대로 넣고 "
                    "세트·반복 수로 조절하세요."
                )
    return (
        "\n[지난주 결과에 따른 난이도 조정 - 실력 수준 규칙보다 우선하며 반드시 따르세요]\n" + "\n".join(lines) + "\n"
    )


def validate_adjustments(
    plan: WeeklyPlan, judgments: list[DrillJudgment] | None, catalog: list[Drill], user: UserInput
) -> list[str]:
    """계획이 지난주 판정을 반영했는지 확인한다. 위반 사유 목록을 돌려주며 빈 목록이면 통과다."""
    if not judgments:
        return []
    by_name = {d.name: d for d in catalog}
    in_plan = {pd.name for day in plan.days for pd in day.drills}
    violations: list[str] = []
    for j in judgments:
        drill = by_name.get(j.drill)
        if drill is None:
            continue
        if j.carry_over:
            if j.drill not in in_plan:
                violations.append(f"지난주 기록이 없던 '{j.drill}'은(는) 다음 주 계획에 다시 넣어야 합니다.")
            continue
        if j.verdict == "유지":
            continue
        candidates = adjustment_candidates(drill, j.verdict, catalog, user)
        if not candidates:
            # 이미 가장 쉽거나 어려워서(또는 장비가 없어서) 바꿀 수 없다. 올릴 곳이 없는 상향은 계획에서 그 메뉴를 유지해야 한다.
            if j.verdict == "상향" and j.drill not in in_plan:
                violations.append(f"'{j.drill}'은(는) 상향이지만 더 어려운 연습 메뉴가 없으므로 이번 주 계획에 그대로 유지해서 넣어야 합니다.")
            continue
        if j.drill in in_plan:
            violations.append(
                f"'{j.drill}'은(는) 지난주 결과가 {j.verdict}이므로 같은 연습 메뉴를 그대로 넣으면 안 됩니다."
            )
        if not any(c.name in in_plan for c in candidates):
            violations.append(
                f"'{j.drill}'의 지난주 결과가 {j.verdict}이므로 대신 {'더 쉬운' if j.verdict == '하향' else '더 어려운'} "
                f"연습 메뉴를 넣어야 합니다. 후보: {', '.join(c.name for c in candidates)}"
            )
    return violations
