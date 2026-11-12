"""가장 어려운 메뉴에서 상향이 나올 때 (T39): 계획은 그 메뉴를 유지하고, 다른 분야 연습 메뉴를 규칙으로 골라 추천한다.

상향 판정이지만 같은 종류(슛 / 슛 외)에서 사용자가 할 수 있는 더 어려운 메뉴가 없으면 올릴 곳이 없다.
(상급 슛 메뉴 성공률 60% 이상, 상급 슛 외 메뉴에서 '쉬웠음'이 가장 많음, 또는 가진 장비로는 더 어려운 메뉴가 없는 경우)
난이도 판정은 그대로 두고, 계획에는 그 메뉴를 유지하게 한다. 추천은 모델이 아니라 아래 규칙으로 고른다.

추천 규칙: 사용자가 할 수 있고(장비) 이미 계획에 없고 유지하는 메뉴와 분야가 다른 메뉴 중에서
  1) 최근 8주 기록이 가장 적은 분야를 먼저 (같으면 슛·드리블·레이업·패스·기타 순)
  2) 그 분야에서 난이도가 가장 높은 메뉴 (같으면 목록 앞쪽)
"""
from dataclasses import dataclass

from src.adjust import adjustment_candidates
from src.models import Drill, UserInput
from src.progress import FIELDS, field_of
from src.records import previous_week_keys
from src.tools import DrillJudgment

COUNT_WEEKS = 8  # 분야별 기록량을 세는 최근 주 수
_RANK = {"초급": 0, "중급": 1, "상급": 2}


@dataclass(frozen=True)
class Recommendation:
    kept: str  # 유지하는 메뉴
    menu: str  # 추천하는 다른 분야 메뉴
    field: str
    difficulty: str
    text: str  # 화면·답변에 보여 줄 안내 문장

    def as_dict(self) -> dict:
        return {"kept": self.kept, "menu": self.menu, "field": self.field, "difficulty": self.difficulty, "text": self.text}


def is_at_top(judgment: DrillJudgment, drill: Drill, catalog: list[Drill], user: UserInput) -> bool:
    """상향 판정인데 올라갈 메뉴가 없다."""
    return judgment.verdict == "상향" and not judgment.carry_over and not adjustment_candidates(drill, "상향", catalog, user)


def field_record_counts(store, user_id: str, week: str, catalog: list[Drill]) -> dict[str, int]:
    """week 바로 앞 8주에 분야별로 입력한 기록 건수(슛 세션 + 자기평가)."""
    field_of_drill = {d.name: field_of(d) for d in catalog}
    counts = {f: 0 for f in FIELDS}
    for per_drill in store.records_for_weeks(user_id, previous_week_keys(week, COUNT_WEEKS)).values():
        for name, rec in per_drill.items():
            if name in field_of_drill:
                counts[field_of_drill[name]] += len(rec["shots"]) + len(rec["ratings"])
    return counts


def recommend_other_fields(
    judgments: list[DrillJudgment] | None,
    catalog: list[Drill],
    user: UserInput,
    counts: dict[str, int],
    in_plan: set[str],
) -> list[Recommendation]:
    """올릴 곳이 없는 상향 판정마다 다른 분야 추천을 하나씩 만든다. 같은 메뉴를 두 번 추천하지 않는다."""
    by_name = {d.name: d for d in catalog}
    owned = set(user.equipment)
    taken = set(in_plan)
    out: list[Recommendation] = []
    for j in judgments or []:
        drill = by_name.get(j.drill)
        if drill is None or not is_at_top(j, drill, catalog, user):
            continue
        own_field = field_of(drill)
        pool = [
            d for d in catalog
            if set(d.requires) <= owned and d.name not in taken and field_of(d) != own_field
            and not (user.is_beginner and d.difficulty != "초급")
        ]
        fields = sorted({field_of(d) for d in pool}, key=lambda f: (counts.get(f, 0), FIELDS.index(f)))
        if not fields:
            continue
        field = fields[0]
        menu = max((d for d in pool if field_of(d) == field), key=lambda d: _RANK[d.difficulty])  # 같은 난이도면 앞쪽
        why = "이미 가장 어려운 난이도(상급)라" if drill.difficulty == "상급" else "지금 가진 장소·장비로 할 수 있는 더 어려운 메뉴가 없어"
        text = (
            f"'{drill.name}'은(는) {why} 이번 주도 그대로 유지해요. "
            f"대신 다른 분야 메뉴 '{menu.name}'({field}, {menu.difficulty})도 해 보세요. (최근 {COUNT_WEEKS}주 {field} 기록 {counts.get(field, 0)}건)"
        )
        taken.add(menu.name)
        out.append(Recommendation(drill.name, menu.name, field, menu.difficulty, text))
    return out
