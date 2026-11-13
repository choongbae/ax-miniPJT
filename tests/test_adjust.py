from src.adjust import adjustment_candidates, format_judgments, validate_adjustments
from src.models import UserInput, WeeklyPlan
from src.tools import DrillJudgment, load_drills

CATALOG = load_drills()
BY_NAME = {d.name: d for d in CATALOG}


def make_user(equipment):
    return UserInput(
        position="가드", level="중급", goals=["3점슛"], days_per_week=3, minutes_per_session=40, equipment=equipment
    )


USER = make_user(["골대", "콘"])


def plan_with(*names):
    drills = [{"name": n, "sets": 3, "reps": 10, "minutes": 10, "purpose": "p"} for n in names]
    return WeeklyPlan.model_validate({"days": [{"day": "월", "drills": drills}]})


LOWER = DrillJudgment("3점 캐치앤슛", "하향", "성공률 20.0% -> 하향")
RAISE = DrillJudgment("3점 캐치앤슛", "상향", "성공률 70.0% -> 상향")


def names(drills):
    return {d.name for d in drills}


def test_lower_candidates_are_easier_shot_menus():
    c = adjustment_candidates(BY_NAME["3점 캐치앤슛"], "하향", CATALOG, USER)
    assert names(c) == {"제자리 자유투", "미드레인지 제자리 점프슛"}


def test_raise_candidates_are_harder_shot_menus_available_with_equipment():
    assert names(adjustment_candidates(BY_NAME["3점 캐치앤슛"], "상향", CATALOG, USER)) == {
        "컷 후 무빙슛", "스텝백 점퍼", "드리블 풀업 3점", "콘 수비 앞 슛",
    }
    # 콘이 없으면 콘이 필요한 상급 슛은 후보에서 빠진다
    only_hoop = adjustment_candidates(BY_NAME["3점 캐치앤슛"], "상향", CATALOG, make_user(["골대"]))
    assert names(only_hoop) == {"스텝백 점퍼", "드리블 풀업 3점"}


def test_candidates_stay_in_the_same_kind():
    c = adjustment_candidates(BY_NAME["양손 크로스오버 드리블"], "하향", CATALOG, USER)
    assert c and all(not d.is_shooting for d in c)


def test_keep_has_no_candidates():
    assert adjustment_candidates(BY_NAME["3점 캐치앤슛"], "유지", CATALOG, USER) == []


def test_case3_lower_requires_replacing_with_easier_shot_menu():
    # 케이스 3: 20% -> 하향. 원래 메뉴가 그대로 있고 쉬운 슛 메뉴가 없으면 위반
    v = validate_adjustments(plan_with("3점 캐치앤슛", "풀업 점퍼"), [LOWER], CATALOG, USER)
    assert len(v) == 2
    assert "그대로 넣으면 안 됩니다" in v[0]
    assert "더 쉬운" in v[1] and "미드레인지 제자리 점프슛" in v[1]


def test_case3_lower_passes_when_replaced_by_easier_menu():
    assert validate_adjustments(plan_with("미드레인지 제자리 점프슛", "풀업 점퍼"), [LOWER], CATALOG, USER) == []


def test_case4_raise_requires_harder_menu():
    assert validate_adjustments(plan_with("3점 캐치앤슛"), [RAISE], CATALOG, USER)
    assert validate_adjustments(plan_with("컷 후 무빙슛"), [RAISE], CATALOG, USER) == []


def test_no_requirement_when_nothing_to_change_to():
    # 이미 가장 어려운(상급) 슛 메뉴는 더 올릴 곳이 없어 같은 메뉴를 그대로 넣어도 된다
    top = DrillJudgment("스텝백 점퍼", "상향", "성공률 70.0% -> 상향")
    assert validate_adjustments(plan_with("스텝백 점퍼"), [top], CATALOG, USER) == []


def test_raise_without_cones_uses_hoop_only_menus():
    # 콘이 없어도 골대만으로 할 수 있는 상급 슛으로 상향할 수 있다
    only_hoop = make_user(["골대"])
    assert validate_adjustments(plan_with("3점 캐치앤슛"), [RAISE], CATALOG, only_hoop)
    assert validate_adjustments(plan_with("스텝백 점퍼"), [RAISE], CATALOG, only_hoop) == []


def test_floor_has_no_requirement():
    # 이미 가장 쉬운(초급) 슛 메뉴는 더 낮출 곳이 없다
    j = DrillJudgment("제자리 자유투", "하향", "성공률 20.0% -> 하향")
    assert validate_adjustments(plan_with("제자리 자유투"), [j], CATALOG, USER) == []


def test_case10_carry_over_must_be_in_next_plan():
    j = DrillJudgment("양손 레이업", "유지", "기록 없음", carry_over=True)
    assert validate_adjustments(plan_with("3점 캐치앤슛"), [j], CATALOG, USER)
    assert validate_adjustments(plan_with("양손 레이업", "3점 캐치앤슛"), [j], CATALOG, USER) == []


def test_keep_verdict_has_no_requirement():
    j = DrillJudgment("3점 캐치앤슛", "유지", "성공률 50.0% -> 유지")
    assert validate_adjustments(plan_with("풀업 점퍼"), [j], CATALOG, USER) == []


def test_no_judgments_means_nothing_to_check():
    assert validate_adjustments(plan_with("3점 캐치앤슛"), None, CATALOG, USER) == []
    assert validate_adjustments(plan_with("3점 캐치앤슛"), [], CATALOG, USER) == []


def test_format_judgments_includes_candidates_and_carry_over():
    carry = DrillJudgment("양손 레이업", "유지", "기록 없음", carry_over=True)
    text = format_judgments([LOWER, carry], CATALOG, USER)
    assert "난이도 조정" in text
    assert "'3점 캐치앤슛': 하향" in text and "미드레인지 제자리 점프슛" in text
    assert "'양손 레이업': 지난주 기록이 없었습니다" in text


def test_format_judgments_empty_is_empty_string():
    assert format_judgments(None, CATALOG, USER) == ""
    assert format_judgments([], CATALOG, USER) == ""


def test_floor_notice_for_lowest_level_drill():
    from src.adjust import floor_notices

    j = DrillJudgment("양손 레이업", "하향", "가장 많은 평가가 '어려웠음'(어려웠음 1번) -> 하향")
    notes = floor_notices([j], CATALOG, USER)
    assert len(notes) == 1 and "'양손 레이업'" in notes[0] and "가장 쉬운 난이도(초급)" in notes[0] and "세트나 횟수를 줄여" in notes[0]
    shot = DrillJudgment("제자리 자유투", "하향", "성공률 20.0% -> 하향")
    assert len(floor_notices([shot], CATALOG, USER)) == 1


def test_floor_notice_only_when_nothing_easier_exists():
    from src.adjust import floor_notices

    # 더 쉬운 메뉴가 있는 하향, 유지, 상향, 기록 없음은 안내하지 않는다
    assert floor_notices([LOWER], CATALOG, USER) == []
    keep = DrillJudgment("양손 레이업", "유지", "적당")
    up = DrillJudgment("스텝백 점퍼", "상향", "성공률 70.0% -> 상향")
    carry = DrillJudgment("양손 레이업", "유지", "기록 없음", carry_over=True)
    assert floor_notices([keep, up, carry], CATALOG, USER) == []
    assert floor_notices(None, CATALOG, USER) == [] and floor_notices([], CATALOG, USER) == []
