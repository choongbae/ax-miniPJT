from src.agent import format_result
from src.models import UserInput, WeeklyPlan
from src.tools import equipment_notices, load_drills

CATALOG = load_drills()


def make_user(level="중급", goals=None, equipment=None):
    return UserInput(
        position="가드",
        level=level,
        goals=goals if goals is not None else [],
        days_per_week=3,
        minutes_per_session=40,
        equipment=equipment if equipment is not None else [],
    )


def test_case9_no_hoop_with_shooting_goal_gets_notice():
    notices = equipment_notices(make_user(goals=["3점슛"], equipment=[]), CATALOG)
    assert len(notices) == 1
    assert "3점슛" in notices[0] and "골대" in notices[0]
    assert "넣지 못했습니다" in notices[0]


def test_case1_has_hoop_gets_no_notice():
    assert equipment_notices(make_user(goals=["3점슛"], equipment=["골대", "콘"]), CATALOG) == []


def test_case6_no_goals_gets_no_notice():
    assert equipment_notices(make_user(level="초급", goals=[], equipment=[]), CATALOG) == []


def test_goal_with_some_usable_menu_gets_no_notice():
    # 드리블 목표: 장비 없이 할 수 있는 연습 메뉴가 있다
    assert equipment_notices(make_user(goals=["왼손 드리블"], equipment=[]), CATALOG) == []


def test_pass_goal_without_wall_gets_notice_about_wall():
    notices = equipment_notices(make_user(goals=["패스"], equipment=["골대"]), CATALOG)
    assert len(notices) == 1 and "벽" in notices[0]


def test_unrecognized_goal_gets_no_notice():
    assert equipment_notices(make_user(goals=["체력"], equipment=[]), CATALOG) == []


def test_notice_is_shown_in_final_answer():
    plan = WeeklyPlan.model_validate(
        {"days": [{"day": "월", "drills": [{"name": "제자리 볼 핸들링", "sets": 3, "reps": 10, "minutes": 30, "purpose": "p"}]}]}
    )
    user = make_user(goals=["3점슛"], equipment=[])
    state = {
        "user": user,
        "plan": plan,
        "status": "ok",
        "violations": [],
        "notices": equipment_notices(user, CATALOG),
    }
    text = format_result(state)
    assert "안내: '3점슛' 목표에 맞는 연습 메뉴는 골대가 있어야 해서" in text
    assert "콘" not in text.split("\n")[2]  # 슛은 골대만 있으면 되므로 콘을 요구하지 않는다
