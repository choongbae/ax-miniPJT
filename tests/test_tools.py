from src.tools import validate_user_input

CASE1 = {
    "position": "가드",
    "level": "중급",
    "goals": ["3점슛"],
    "days_per_week": 3,
    "minutes_per_session": 40,
    "equipment": ["골대", "콘"],
}


def test_case1_passes():
    user, errors = validate_user_input(CASE1)
    assert errors == []
    assert user is not None and user.days_per_week == 3


def test_case17_eight_days_gives_korean_range_message():
    # 케이스 17: 주 8일 하루 40분
    user, errors = validate_user_input({**CASE1, "days_per_week": 8})
    assert user is None
    assert errors == ["주 연습일은 1~7 사이의 정수여야 합니다."]


def test_non_numeric_minutes():
    user, errors = validate_user_input({**CASE1, "minutes_per_session": "많이"})
    assert user is None
    assert errors == ["회당 연습 시간은 1분 이상의 정수여야 합니다."]


def test_zero_minutes():
    user, errors = validate_user_input({**CASE1, "minutes_per_session": 0})
    assert user is None
    assert "회당 연습 시간" in errors[0]


def test_invalid_level():
    user, errors = validate_user_input({**CASE1, "level": "입문"})
    assert user is None
    assert errors == ["실력 수준은 초급, 중급, 상급 중 하나여야 합니다."]


def test_missing_field_asks_for_input():
    raw = {k: v for k, v in CASE1.items() if k != "days_per_week"}
    user, errors = validate_user_input(raw)
    assert user is None
    assert errors == ["주 연습일을(를) 입력해 주세요."]


def test_multiple_errors_reported_together():
    user, errors = validate_user_input({**CASE1, "days_per_week": 0, "level": "입문"})
    assert user is None
    assert len(errors) == 2


# --- 장비 때문에 뺀 목표를 목적 문구에 쓰면 위반 (T31, 평가 케이스 9) -------------------------------------

def test_purpose_must_not_claim_a_goal_dropped_for_missing_equipment():
    from src.models import UserInput, WeeklyPlan
    from src.tools import load_drills, unsupported_goals, validate_goal_claims

    catalog = load_drills()
    user = UserInput(position="미정", level="초급", goals=["3점슛"], days_per_week=1, minutes_per_session=30, equipment=[])
    assert [g for g, _ in unsupported_goals(user, catalog)] == ["3점슛"]

    def plan(purpose):
        return WeeklyPlan.model_validate({"days": [{"day": "월", "drills": [{"name": "슛 폼 연습", "sets": 3, "reps": 15, "minutes": 15, "purpose": purpose}]}]})

    bad = validate_goal_claims(plan("3점슛을 위한 기본 슛 자세를 익혀요"), user, catalog)
    assert len(bad) == 1 and "3점슛" in bad[0] and "슛 폼 연습" in bad[0]
    assert validate_goal_claims(plan("골대 없이 올바른 슛 자세를 몸에 익혀요"), user, catalog) == []
    with_hoop = user.model_copy(update={"equipment": ["골대"]})
    assert validate_goal_claims(plan("3점슛을 위한 기본 슛 자세를 익혀요"), with_hoop, catalog) == []  # 골대가 있으면 뺀 목표가 아니다


def test_menus_of_a_goal_dropped_for_equipment_are_dropped_even_if_they_need_no_equipment():
    from src.agent import available_drills
    from src.models import UserInput
    from src.tools import load_drills

    catalog = load_drills()
    no_hoop = UserInput(position="미정", level="초급", goals=["3점슛"], days_per_week=2, minutes_per_session=30, equipment=[])
    names = {d.name for d in available_drills(no_hoop, catalog)}
    assert names and not any("슛" in n for n in names)  # '슛 폼 연습'도 빠진다
    assert "제자리 볼 핸들링" in names  # 다른 연습은 그대로
    other_goal = no_hoop.model_copy(update={"goals": ["왼손 드리블"]})
    assert "슛 폼 연습" in {d.name for d in available_drills(other_goal, catalog)}  # 슛이 목표가 아니면 유지
    with_hoop = no_hoop.model_copy(update={"equipment": ["골대"]})
    assert "슛 폼 연습" in {d.name for d in available_drills(with_hoop, catalog)}
