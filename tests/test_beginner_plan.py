from src.agent import available_drills, build_prompt_values, prompt
from src.models import UserInput, WeeklyPlan
from src.tools import load_drills, validate_plan

CATALOG = load_drills()


def make_user(equipment, beginner=True, level="초급"):
    return UserInput(
        position="미정" if beginner else "가드",
        level=level,
        is_beginner=beginner,
        goals=[],
        days_per_week=3,
        minutes_per_session=30,
        equipment=equipment,
    )


def plan_with(*names):
    drills = [{"name": n, "sets": 3, "reps": 10, "minutes": 10, "purpose": "p"} for n in names]
    return WeeklyPlan.model_validate({"days": [{"day": "월", "drills": drills}]})


def test_beginner_gets_only_beginner_level_menus():
    drills = available_drills(make_user(["골대", "콘", "벽"]), CATALOG)
    assert drills and all(d.difficulty == "초급" for d in drills)


def test_non_beginner_keeps_all_levels():
    drills = available_drills(make_user(["골대", "콘", "벽"], beginner=False, level="중급"), CATALOG)
    assert {d.difficulty for d in drills} == {"초급", "중급", "상급"}


def test_case26_beginner_with_hoop_gets_three_basics_available():
    names = {d.name for d in available_drills(make_user(["골대", "콘"]), CATALOG)}
    assert {"제자리 자유투", "제자리 볼 핸들링", "양손 레이업"} <= names  # 슛 폼 · 볼 핸들링 · 레이업


def test_case27_beginner_ball_only_gets_ball_only_beginner_menus():
    drills = available_drills(make_user([]), CATALOG)
    assert len(drills) >= 7
    assert all(not d.requires and d.difficulty == "초급" for d in drills)
    assert {"슛 폼 연습", "레이업 스텝 연습"} <= {d.name for d in drills}


def test_prompt_has_beginner_note_only_for_beginner():
    beginner_values = build_prompt_values(make_user(["골대"]), CATALOG)
    assert "초보자 옵션" in beginner_values["beginner"]
    assert "쉬운 말" in beginner_values["beginner"]
    normal = build_prompt_values(make_user(["골대"], beginner=False, level="중급"), CATALOG)
    assert normal["beginner"] == ""
    assert prompt.format_messages(**beginner_values)  # 템플릿이 오류 없이 만들어진다


def test_beginner_prompt_shows_position_as_undecided():
    assert build_prompt_values(make_user([]), CATALOG)["position"] == "미정"


def test_validator_flags_non_beginner_menu_in_beginner_plan():
    v = validate_plan(plan_with("제자리 자유투", "풀업 점퍼"), make_user(["골대"]), CATALOG)
    assert len(v) == 1
    assert "풀업 점퍼" in v[0] and "초급 연습 메뉴만" in v[0]


def test_validator_passes_beginner_menus_only():
    assert validate_plan(plan_with("제자리 자유투", "양손 레이업", "제자리 볼 핸들링"), make_user(["골대"]), CATALOG) == []


def test_validator_does_not_apply_beginner_rule_to_others():
    other = make_user(["골대"], beginner=False, level="중급")
    assert validate_plan(plan_with("풀업 점퍼"), other, CATALOG) == []
