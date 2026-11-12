from src.tools import validate_user_input

BASE = {
    "goals": [],
    "days_per_week": 3,
    "minutes_per_session": 30,
    "equipment": ["골대", "콘"],
}


def test_case26_beginner_passes_without_level_and_position():
    user, errors = validate_user_input({**BASE, "is_beginner": True})
    assert errors == []
    assert user.level == "초급"
    assert user.position == "미정"
    assert user.is_beginner is True


def test_beginner_level_is_forced_to_beginner_even_if_other_level_given():
    user, errors = validate_user_input({**BASE, "is_beginner": True, "level": "상급"})
    assert errors == [] and user.level == "초급"


def test_beginner_keeps_position_if_user_gave_one():
    user, _ = validate_user_input({**BASE, "is_beginner": True, "position": "센터"})
    assert user.position == "센터"


def test_non_beginner_still_needs_level_and_position():
    user, errors = validate_user_input({**BASE, "is_beginner": False})
    assert user is None
    assert "실력 수준을(를) 입력해 주세요." in errors
    assert "포지션을(를) 입력해 주세요." in errors


def test_missing_is_beginner_means_not_beginner():
    user, errors = validate_user_input({**BASE, "position": "가드", "level": "중급"})
    assert errors == [] and user.is_beginner is False


def test_beginner_still_validates_other_fields():
    user, errors = validate_user_input({**BASE, "is_beginner": True, "days_per_week": 8})
    assert user is None
    assert errors == ["주 연습일은 1~7 사이의 정수여야 합니다."]
