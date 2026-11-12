"""도메인 도구.

규칙 판정과 계산은 LLM이 아니라 이 파일의 파이썬 코드로 한다.
예정: 슛 누적 성공률 -> 난이도(하향/유지/상향), 슛 외 자기평가 최빈값 -> 난이도,
계획 검증(연습일 수 <= N, 일별 시간 합 <= M, 없는 장비 연습 메뉴 제외).
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from src.models import Drill, UserInput, WeeklyPlan

Verdict = Literal["하향", "유지", "상향"]
MIN_SHOT_ATTEMPTS = 20  # 1주 시도 합계가 이보다 적으면 표본이 적어 난이도를 유지한다

DRILLS_PATH = Path(__file__).resolve().parent.parent / "data" / "drills.json"


def load_drills(path: Path = DRILLS_PATH) -> list[Drill]:
    """연습 메뉴 목록(data/drills.json)을 읽는다."""
    return [Drill.model_validate(d) for d in json.loads(path.read_text(encoding="utf-8"))]

# 필드별 한국어 안내. 모델이 내는 영어 오류 대신 사용자에게 보여 준다.
_FIELD_LABEL = {
    "position": "포지션",
    "level": "실력 수준",
    "goals": "약점·목표",
    "days_per_week": "주 연습일",
    "minutes_per_session": "회당 연습 시간",
    "equipment": "장소·장비",
}
_INVALID_MESSAGE = {
    "position": "포지션은 가드, 포워드, 센터 중 하나여야 합니다.",
    "level": "실력 수준은 초급, 중급, 상급 중 하나여야 합니다.",
    "days_per_week": "주 연습일은 1~7 사이의 정수여야 합니다.",
    "minutes_per_session": "회당 연습 시간은 1분 이상의 정수여야 합니다.",
    "goals": "약점·목표는 목록 형태로 입력해 주세요.",
    "equipment": "장소·장비는 목록 형태로 입력해 주세요.",
}


def validate_user_input(raw: dict) -> tuple[UserInput | None, list[str]]:
    """입력을 검증한다. 통과하면 (UserInput, []), 실패하면 (None, 한국어 안내 목록).

    초보자 옵션(is_beginner)이면 실력 수준은 초급으로 자동 정하고 포지션은 묻지 않는다('미정').
    """
    data = dict(raw)
    if data.get("is_beginner"):
        data["level"] = "초급"
        data["position"] = data.get("position") or "미정"
    try:
        return UserInput.model_validate(data), []
    except ValidationError as e:
        messages: list[str] = []
        for err in e.errors():
            field = str(err["loc"][0]) if err["loc"] else ""
            if err["type"] == "missing":
                msg = f"{_FIELD_LABEL.get(field, field)}을(를) 입력해 주세요."
            else:
                msg = _INVALID_MESSAGE.get(field, f"{field} 값이 올바르지 않습니다.")
            if msg not in messages:
                messages.append(msg)
        return None, messages


def validate_plan(plan: WeeklyPlan, user: UserInput, catalog: list[Drill]) -> list[str]:
    """계획이 규칙을 지키는지 확인한다. 위반 사유 목록을 반환하며, 빈 목록이면 통과다.

    규칙: 연습일 수 <= 주 N일, 하루 연습 메뉴 시간 합 <= 회당 M분,
    연습 메뉴 목록에 있는 연습 메뉴만 사용, 없다고 입력한 장소·장비가 필요한 연습 메뉴는 제외.
    """
    violations: list[str] = []
    by_name = {d.name: d for d in catalog}
    owned = set(user.equipment)

    if len(plan.days) > user.days_per_week:
        violations.append(
            f"연습일이 {len(plan.days)}일이라 주 {user.days_per_week}일을 넘습니다."
        )

    for day in plan.days:
        if day.total_minutes > user.minutes_per_session:
            violations.append(
                f"{day.day}의 연습 메뉴 시간 합이 {day.total_minutes}분이라 "
                f"회당 {user.minutes_per_session}분을 넘습니다."
            )
        for pd in day.drills:
            drill = by_name.get(pd.name)
            if drill is None:
                violations.append(f"{day.day}의 '{pd.name}'은(는) 연습 메뉴 목록에 없습니다.")
                continue
            missing = [r for r in drill.requires if r not in owned]
            if missing:
                violations.append(
                    f"{day.day}의 '{pd.name}'은(는) {', '.join(missing)}이(가) 필요하지만 없다고 입력되었습니다."
                )
            if user.is_beginner and drill.difficulty != "초급":
                violations.append(
                    f"{day.day}의 '{pd.name}'은(는) {drill.difficulty} 연습 메뉴라서 초보자 계획에는 초급 연습 메뉴만 넣을 수 있습니다."
                )
    return violations


# 약점·목표에 들어 있는 말 -> 그 목표에 해당하는 연습 메뉴를 고르는 조건.
# 지금은 키워드로 판단한다 (묶음 3에서 검색으로 바뀔 수 있다).
_GOAL_MATCHERS = {
    "슛": lambda d: d.is_shooting,
    "드리블": lambda d: "드리블" in d.name or "핸들링" in d.name,
    "레이업": lambda d: "레이업" in d.name,
    "패스": lambda d: "패스" in d.name,
}


def unsupported_goals(user: UserInput, catalog: list[Drill]) -> list[tuple[str, list[str]]]:
    """장소·장비 부족으로 맞는 연습 메뉴가 모두 빠진 목표와, 그 목표에 가장 적게 부족한 장비 조합. [(목표, [부족한 장비])]

    목표에 해당하는 연습 메뉴 중 하나라도 쓸 수 있으면 포함하지 않는다.
    """
    owned = set(user.equipment)
    out: list[tuple[str, list[str]]] = []
    for goal in user.goals:
        related: list[Drill] = []
        for keyword, matches in _GOAL_MATCHERS.items():
            if keyword in goal:
                related += [d for d in catalog if matches(d) and d not in related]
        if not related or any(set(d.requires) <= owned for d in related):
            continue
        # 연습 메뉴마다 부족한 장비를 구하고, 가장 적게 부족한 조합을 안내한다 (예: 슛은 골대만 있으면 된다)
        missing = min((sorted(set(d.requires) - owned) for d in related), key=lambda m: (len(m), m))
        out.append((goal, missing))
    return out


def drop_unsupported_goal_menus(drills: list[Drill], user: UserInput, catalog: list[Drill]) -> list[Drill]:
    """장비 때문에 뺀 목표의 연습 메뉴는 장비 없이 되는 것도 함께 뺀다. 안내("이 목표 메뉴는 넣지 못했다")와 계획이 어긋나지 않게 한다.

    예: 골대 없이 3점슛이 목표면 `슛 폼 연습`처럼 이름에 '슛'이 든 메뉴도 넣지 않고, 공만으로 되는 다른 연습으로 채운다."""
    keywords = {kw for goal, _ in unsupported_goals(user, catalog) for kw in _GOAL_MATCHERS if kw in goal}
    return [d for d in drills if not any(kw in d.name for kw in keywords)]


def equipment_notices(user: UserInput, catalog: list[Drill]) -> list[str]:
    """목표에 맞는 연습 메뉴가 장소·장비 부족으로 모두 빠진 경우에만 안내 문구를 만든다."""
    notices: list[str] = []
    for goal, missing in unsupported_goals(user, catalog):
        need = ", ".join(missing)
        notices.append(
            f"'{goal}' 목표에 맞는 연습 메뉴는 {need}{_subject_particle(need)} 있어야 해서 이번 계획에는 넣지 못했습니다. "
            "대신 지금 가진 장소·장비로 할 수 있는 연습 메뉴로 구성했습니다."
        )
    return notices


def validate_goal_claims(plan: WeeklyPlan, user: UserInput, catalog: list[Drill]) -> list[str]:
    """장비 때문에 넣지 못한 목표를 연습 메뉴의 목적 문구가 달성한다고 말하면 위반이다 (같은 답변의 안내와 어긋난다)."""
    violations = []
    for goal, _ in unsupported_goals(user, catalog):
        for day in plan.days:
            for drill in day.drills:
                if goal in drill.purpose:
                    violations.append(
                        f"{day.day}요일 '{drill.name}'의 목적에 장비 부족으로 뺀 목표 '{goal}'이 적혀 있습니다. 이 목표를 목적에 쓰지 말고 연습 메뉴가 실제로 하는 일만 쓰세요."
                    )
    return violations


def _subject_particle(word: str) -> str:
    """마지막 글자의 받침 유무로 '이'/'가'를 고른다."""
    code = ord(word[-1]) - 0xAC00
    return "이" if 0 <= code < 11172 and code % 28 else "가"


# ---------------------------------------------------------------------------
# 난이도 판정 (SERVICE.md 3장 "슛 난이도 판정 세부 기준"). LLM이 아니라 정수 계산으로 한다.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Judgment:
    verdict: Verdict
    reason: str
    rate: float | None = None  # 소수 첫째 자리로 반올림한 성공률(%). 슛 판정에서만 쓴다.


def _rate_tenths(makes: int, attempts: int) -> int:
    """성공률(%)을 소수 첫째 자리에서 반올림해 10배한 정수로 돌려준다. (39.95% -> 400)"""
    return (makes * 2000 + attempts) // (2 * attempts)


def judge_shot_difficulty(
    attempts: int, makes: int, past_weeks: list[tuple[int, int]] | None = None
) -> Judgment:
    """한 슛 연습 메뉴의 1주 시도·성공 합계로 다음 주 난이도를 판정한다.

    past_weeks: 최근 4주(이번 주 제외) 각 주의 (시도 합계, 성공 합계). 고르는 일은 호출하는 쪽이 한다.
    """
    if attempts < 0 or makes < 0 or makes > attempts:
        raise ValueError(f"시도 {attempts}회, 성공 {makes}회는 올바른 값이 아닙니다.")
    if attempts == 0:
        return Judgment("유지", "이번 주 슛 기록이 없어 난이도를 유지합니다.")

    tenths = _rate_tenths(makes, attempts)
    rate = tenths / 10
    if attempts < MIN_SHOT_ATTEMPTS:
        return Judgment(
            "유지", f"시도가 {attempts}회로 {MIN_SHOT_ATTEMPTS}회 미만이라 표본이 적어 유지합니다. {MIN_SHOT_ATTEMPTS}회 이상 기록하면 판정할 수 있어요.", rate
        )

    def reached(boundary: int) -> bool:
        return any(a >= MIN_SHOT_ATTEMPTS and _rate_tenths(m, a) >= boundary for a, m in (past_weeks or []))

    effective, note = tenths, ""
    if 390 <= tenths < 400 and reached(400):
        effective, note = 400, " (최근 4주에 40% 이상인 주가 있어 40%로 보정)"
    elif 590 <= tenths < 600 and reached(600):
        effective, note = 600, " (최근 4주에 60% 이상인 주가 있어 60%로 보정)"

    verdict: Verdict = "하향" if effective < 400 else ("유지" if effective < 600 else "상향")
    return Judgment(verdict, f"성공률 {rate:.1f}%{note} -> {verdict}", rate)


# 슛 외 연습 메뉴의 자기평가 -> 다음 주 난이도
_RATING_VERDICT: dict[str, Verdict] = {"쉬웠음": "상향", "적당": "유지", "어려웠음": "하향"}


def judge_rating_difficulty(ratings: list[str]) -> Judgment:
    """슛 외 연습 메뉴: 1주 동안 가장 많이 나온 자기평가로 판정한다. 동수이면 유지한다."""
    unknown = [r for r in ratings if r not in _RATING_VERDICT]
    if unknown:
        raise ValueError(f"자기평가는 쉬웠음, 적당, 어려웠음 중 하나여야 합니다: {unknown}")
    if not ratings:
        return Judgment("유지", "이번 주 자기평가 기록이 없어 난이도를 유지합니다.")

    counts = {r: ratings.count(r) for r in _RATING_VERDICT}
    top = max(counts.values())
    modes = [r for r, c in counts.items() if c == top]
    summary = ", ".join(f"{r} {c}번" for r, c in counts.items() if c)
    if len(modes) > 1:
        return Judgment("유지", f"자기평가가 동수({summary})라서 난이도를 유지합니다.")
    return Judgment(_RATING_VERDICT[modes[0]], f"가장 많은 평가가 '{modes[0]}'({summary}) -> {_RATING_VERDICT[modes[0]]}")


@dataclass(frozen=True)
class DrillJudgment:
    """한 연습 메뉴의 지난주 결과. carry_over가 True이면 기록이 없어 다음 주에 같은 메뉴를 다시 넣어야 한다."""

    drill: str
    verdict: Verdict
    reason: str
    carry_over: bool = False


def judge_drill(
    drill: Drill,
    shots: list[tuple[int, int]] | None = None,
    ratings: list[str] | None = None,
    past_weeks: list[tuple[int, int]] | None = None,
) -> DrillJudgment:
    """연습 메뉴 하나의 지난주 기록으로 다음 주 난이도를 판정한다.

    shots: 그 주 슛 기록 (시도, 성공)의 목록. ratings: 그 주 자기평가 목록. 슛 연습 메뉴는 shots, 슛 외는 ratings를 본다.
    기록이 하나도 없으면 난이도를 바꾸지 않고 다음 주에 다시 넣을 대상(carry_over)으로 표시한다.
    """
    if drill.is_shooting:
        attempts = sum(a for a, _ in shots or [])
        makes = sum(m for _, m in shots or [])
        has_record = attempts > 0
        judgment = judge_shot_difficulty(attempts, makes, past_weeks) if has_record else None
    else:
        has_record = bool(ratings)
        judgment = judge_rating_difficulty(ratings or []) if has_record else None

    if judgment is None:
        return DrillJudgment(
            drill.name, "유지", "이번 주 기록이 없어 난이도를 바꾸지 않고 다음 주에 다시 넣습니다.", carry_over=True
        )
    return DrillJudgment(drill.name, judgment.verdict, judgment.reason)
