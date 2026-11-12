from src.agent import available_drills, build_prompt_values, prompt
from src.models import UserInput
from src.tools import load_drills

CATALOG = load_drills()


def make_user(equipment):
    return UserInput(
        position="가드",
        level="중급",
        goals=["3점슛"],
        days_per_week=3,
        minutes_per_session=40,
        equipment=equipment,
    )


def test_available_drills_excludes_missing_equipment():
    names = {d.name for d in available_drills(make_user(["골대", "콘"]), CATALOG)}
    assert "3점 캐치앤슛" in names
    assert "벽 패스" not in names  # 벽 없음


def test_no_hoop_user_gets_no_shooting_drills():
    drills = available_drills(make_user([]), CATALOG)
    assert drills and not any(d.is_shooting for d in drills)


def test_prompt_values_cover_all_template_variables():
    values = build_prompt_values(make_user(["골대", "콘"]), CATALOG)
    assert set(prompt.input_variables) <= set(values)
    assert values["days"] == 3 and values["minutes"] == 40
    assert "3점 캐치앤슛" in values["drills"]


def test_violations_are_included_for_regeneration():
    values = build_prompt_values(make_user(["골대"]), CATALOG, ["연습일이 4일이라 주 3일을 넘습니다."])
    assert "연습일이 4일이라 주 3일을 넘습니다." in values["violations"]


def test_prompt_renders_without_error():
    messages = prompt.format_messages(**build_prompt_values(make_user(["골대", "콘"]), CATALOG))
    assert len(messages) == 2
