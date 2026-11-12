from src.agent import collect_input, format_result, main, split_items
from src.models import UserInput, WeeklyPlan

USER = UserInput(
    position="가드",
    level="중급",
    goals=["3점슛"],
    days_per_week=3,
    minutes_per_session=40,
    equipment=["골대", "콘"],
)
PLAN = WeeklyPlan.model_validate(
    {
        "days": [
            {
                "day": "월",
                "drills": [
                    {"name": "3점 캐치앤슛", "sets": 4, "reps": 10, "minutes": 20, "purpose": "타이밍 익히기"},
                    {"name": "양손 레이업", "sets": 3, "reps": 8, "minutes": 20, "purpose": "발 순서 확인"},
                ],
            }
        ]
    }
)


def test_split_items():
    assert split_items("골대, 콘") == ["골대", "콘"]
    assert split_items("") == []
    assert split_items("없음") == []
    assert split_items("3점슛, 왼손 드리블") == ["3점슛", "왼손 드리블"]


def test_format_ok_shows_day_and_drill_details():
    text = format_result({"user": USER, "plan": PLAN, "status": "ok", "violations": []})
    assert "[월] 총 40분" in text
    assert "1. 3점 캐치앤슛 - 4세트 × 10회 (20분)" in text
    assert "목적: 타이밍 익히기" in text


def test_format_failed_hides_plan_and_shows_reasons():
    text = format_result(
        {"user": USER, "plan": PLAN, "status": "failed", "violations": ["연습일이 4일이라 주 3일을 넘습니다."]}
    )
    assert "만들지 못했습니다" in text
    assert "연습일이 4일이라 주 3일을 넘습니다." in text
    assert "3점 캐치앤슛" not in text  # 규칙을 어긴 계획은 보여 주지 않는다


def feeder(answers):
    it = iter(answers)
    return lambda prompt: next(it)


def test_collect_input_parses_answers():
    raw = collect_input(feeder(["가드", "중급", "3점슛", "3", "40", "골대, 콘"]))
    assert raw["goals"] == ["3점슛"] and raw["equipment"] == ["골대", "콘"]
    assert raw["days_per_week"] == "3"


def test_main_success_prints_plan_and_returns_zero():
    out = []
    code = main(
        input_fn=feeder(["가드", "중급", "3점슛", "3", "40", "골대, 콘"]),
        run=lambda user: {"user": user, "plan": PLAN, "status": "ok", "violations": []},
        out=out.append,
    )
    assert code == 0
    assert any("[월] 총 40분" in line for line in out)


def test_main_invalid_input_stops_before_running_agent():
    out = []

    def must_not_run(user):
        raise AssertionError("입력이 틀리면 에이전트를 실행하면 안 된다")

    code = main(
        input_fn=feeder(["가드", "중급", "", "8", "40", ""]),  # 케이스 17: 주 8일
        run=must_not_run,
        out=out.append,
    )
    assert code == 1
    assert "- 주 연습일은 1~7 사이의 정수여야 합니다." in out
