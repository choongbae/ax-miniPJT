from src.models import UserInput, WeeklyPlan
from src.tools import load_drills, validate_plan

CATALOG = load_drills()

# 케이스 1: 가드, 중급, 3점슛, 주 3일 x 40분, 골대·콘
USER = UserInput(
    position="가드",
    level="중급",
    goals=["3점슛"],
    days_per_week=3,
    minutes_per_session=40,
    equipment=["골대", "콘"],
)


def drill(name, minutes):
    return {"name": name, "sets": 4, "reps": 10, "minutes": minutes, "purpose": "p"}


def day(label, *drills):
    return {"day": label, "drills": list(drills)}


def plan(*days):
    return WeeklyPlan.model_validate({"days": list(days)})


GOOD = plan(
    day("월", drill("3점 캐치앤슛", 20), drill("왼손 콘 지그재그 드리블", 20)),
    day("수", drill("풀업 점퍼", 25), drill("양손 레이업", 15)),
    day("금", drill("3점 캐치앤슛", 20)),
)


def test_valid_plan_passes():
    assert validate_plan(GOOD, USER, CATALOG) == []


def test_too_many_days():
    p = plan(
        day("월", drill("3점 캐치앤슛", 20)),
        day("화", drill("3점 캐치앤슛", 20)),
        day("수", drill("3점 캐치앤슛", 20)),
        day("목", drill("3점 캐치앤슛", 20)),
    )
    v = validate_plan(p, USER, CATALOG)
    assert v == ["연습일이 4일이라 주 3일을 넘습니다."]


def test_day_minutes_over_limit():
    p = plan(day("월", drill("3점 캐치앤슛", 25), drill("풀업 점퍼", 20)))
    v = validate_plan(p, USER, CATALOG)
    assert v == ["월의 연습 메뉴 시간 합이 45분이라 회당 40분을 넘습니다."]


def test_missing_equipment_drill_is_flagged():
    # 벽이 있다고 입력하지 않았는데 벽 패스를 넣은 경우
    p = plan(day("월", drill("벽 패스", 20)))
    v = validate_plan(p, USER, CATALOG)
    assert len(v) == 1 and "벽" in v[0] and "벽 패스" in v[0]


def test_no_hoop_user_cannot_get_shooting_drill():
    # 케이스 9: 골대 없음인데 슛 연습 메뉴가 들어간 경우
    no_hoop = USER.model_copy(update={"equipment": []})
    p = plan(day("월", drill("3점 캐치앤슛", 20)))
    v = validate_plan(p, no_hoop, CATALOG)
    assert len(v) == 1 and "골대" in v[0]


def test_unknown_drill_name_is_flagged():
    p = plan(day("월", drill("덩크 연습", 20)))
    v = validate_plan(p, USER, CATALOG)
    assert v == ["월의 '덩크 연습'은(는) 연습 메뉴 목록에 없습니다."]


def test_multiple_violations_reported_together():
    p = plan(
        day("월", drill("3점 캐치앤슛", 30), drill("풀업 점퍼", 30)),
        day("화", drill("벽 패스", 20)),
        day("수", drill("양손 레이업", 20)),
        day("목", drill("양손 레이업", 20)),
    )
    v = validate_plan(p, USER, CATALOG)
    assert len(v) == 3  # 4일, 월 60분, 화 벽 패스
