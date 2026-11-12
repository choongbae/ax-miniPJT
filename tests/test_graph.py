from src.agent import MAX_RETRIES, run_agent
from src.models import UserInput, WeeklyPlan
from src.tools import load_drills

CATALOG = load_drills()
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


GOOD = WeeklyPlan.model_validate(
    {
        "days": [
            {"day": "월", "drills": [drill("3점 캐치앤슛", 20), drill("왼손 콘 지그재그 드리블", 20)]},
            {"day": "수", "drills": [drill("풀업 점퍼", 25), drill("양손 레이업", 15)]},
            {"day": "금", "drills": [drill("3점 캐치앤슛", 20)]},
        ]
    }
)
# 하루 시간 합 60분으로 규칙을 어긴 계획
BAD = WeeklyPlan.model_validate(
    {"days": [{"day": "월", "drills": [drill("3점 캐치앤슛", 30), drill("풀업 점퍼", 30)]}]}
)


def make_fake(plans):
    """호출될 때마다 plans를 차례로 돌려주는 가짜 생성 함수. 받은 위반 사유도 기록한다."""
    calls = []

    def fake(user, catalog, violations, judgments=None, menus=None):
        calls.append(violations)
        return plans[min(len(calls) - 1, len(plans) - 1)]

    return fake, calls


def test_valid_first_plan_finishes_in_one_attempt():
    fake, calls = make_fake([GOOD])
    state = run_agent(USER, CATALOG, generate_fn=fake)
    assert state["status"] == "ok"
    assert state["attempts"] == 1
    assert calls == [None]


def test_violation_triggers_regeneration_with_reasons():
    fake, calls = make_fake([BAD, GOOD])
    state = run_agent(USER, CATALOG, generate_fn=fake)
    assert state["status"] == "ok"
    assert state["attempts"] == 2
    assert calls[0] is None
    assert calls[1] and "60분" in calls[1][0]  # 위반 사유가 두 번째 생성에 전달된다
    assert any("이전 위반 사유 반영" in line for line in state["log"])


def test_gives_up_after_max_retries():
    fake, calls = make_fake([BAD])
    state = run_agent(USER, CATALOG, generate_fn=fake)
    assert state["status"] == "failed"
    assert state["attempts"] == 1 + MAX_RETRIES
    assert len(calls) == 1 + MAX_RETRIES
    assert state["violations"]
    assert "만들지 못했습니다" in state["log"][-1]


def test_plan_that_ignores_last_weeks_lowering_is_regenerated():
    from src.tools import DrillJudgment

    lower = DrillJudgment("3점 캐치앤슛", "하향", "성공률 20.0% -> 하향")
    easier = WeeklyPlan.model_validate(
        {
            "days": [
                {"day": "월", "drills": [drill("미드레인지 제자리 점프슛", 20), drill("풀업 점퍼", 20)]},
            ]
        }
    )
    fake, calls = make_fake([GOOD, easier])  # GOOD에는 3점 캐치앤슛이 그대로 있다
    state = run_agent(USER, CATALOG, generate_fn=fake, judgments=[lower])
    assert state["status"] == "ok"
    assert state["attempts"] == 2
    assert any("그대로 넣으면 안 됩니다" in v for v in calls[1])  # 두 번째 생성에 사유가 전달된다


def test_judgments_are_passed_to_generator():
    from src.tools import DrillJudgment

    seen = []

    def fake(user, catalog, violations, judgments=None, menus=None):
        seen.append(judgments)
        return GOOD

    keep = DrillJudgment("3점 캐치앤슛", "유지", "성공률 50.0% -> 유지")
    run_agent(USER, CATALOG, generate_fn=fake, judgments=[keep])
    assert seen == [[keep]]
