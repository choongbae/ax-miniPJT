import pytest
from pydantic import ValidationError

from src.models import Drill, UserInput, WeeklyPlan

CASE1 = {
    "position": "가드",
    "level": "중급",
    "goals": ["3점슛"],
    "days_per_week": 3,
    "minutes_per_session": 40,
    "equipment": ["골대", "콘"],
}


def test_user_input_case1_passes():
    u = UserInput(**CASE1)
    assert u.level == "중급"
    assert u.days_per_week == 3


@pytest.mark.parametrize("level", ["입문", "초보", "", "intermediate"])
def test_invalid_level_rejected(level):
    with pytest.raises(ValidationError):
        UserInput(**{**CASE1, "level": level})


@pytest.mark.parametrize("days", [0, 8])
def test_days_out_of_range_rejected(days):
    with pytest.raises(ValidationError):
        UserInput(**{**CASE1, "days_per_week": days})


def test_minutes_must_be_positive():
    with pytest.raises(ValidationError):
        UserInput(**{**CASE1, "minutes_per_session": 0})


def test_drill_catalog_item():
    d = Drill(
        name="3점 캐치앤슛",
        purpose="패스를 받아 바로 쏘는 타이밍 익히기",
        requires=["골대"],
        difficulty="중급",
        is_shooting=True,
    )
    assert d.is_shooting


def test_weekly_plan_total_minutes():
    plan = WeeklyPlan.model_validate(
        {
            "days": [
                {
                    "day": "월",
                    "drills": [
                        {"name": "A", "sets": 5, "reps": 10, "minutes": 20, "purpose": "p"},
                        {"name": "B", "sets": 4, "reps": 2, "minutes": 20, "purpose": "p"},
                    ],
                }
            ]
        }
    )
    assert plan.days[0].total_minutes == 40


def test_plan_requires_drills_and_positive_numbers():
    with pytest.raises(ValidationError):
        WeeklyPlan.model_validate({"days": [{"day": "월", "drills": []}]})
    with pytest.raises(ValidationError):
        WeeklyPlan.model_validate(
            {"days": [{"day": "월", "drills": [{"name": "A", "sets": 0, "reps": 1, "minutes": 5, "purpose": "p"}]}]}
        )
