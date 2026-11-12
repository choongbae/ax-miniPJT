import pytest

from src.tools import judge_shot_difficulty as judge


def test_case2_exactly_40_percent_keeps():
    # 케이스 2: 월 50회 중 10회 + 목 50회 중 30회 = 100회 중 40회
    j = judge(100, 40)
    assert (j.verdict, j.rate) == ("유지", 40.0)


def test_case3_20_percent_lowers():
    assert judge(50, 10).verdict == "하향"


def test_case4_70_percent_raises():
    assert judge(60, 42).verdict == "상향"


def test_case15_exactly_60_percent_raises():
    assert judge(100, 60).verdict == "상향"


def test_just_below_boundaries_without_history():
    assert judge(200, 79).verdict == "하향"  # 39.5%
    assert judge(200, 119).verdict == "유지"  # 59.5%


def test_case22_under_20_attempts_keeps():
    j = judge(15, 3)
    assert j.verdict == "유지" and "20회 미만" in j.reason


def test_exactly_20_attempts_is_judged():
    assert judge(20, 4).verdict == "하향"  # 20%
    assert judge(19, 4).verdict == "유지"  # 19회는 표본 부족


def test_zero_attempts_is_no_record():
    j = judge(0, 0)
    assert j.verdict == "유지" and j.rate is None


def test_case23_near_40_with_past_week_at_or_above_40_keeps():
    j = judge(200, 79, past_weeks=[(100, 45)])
    assert j.verdict == "유지" and "40%로 보정" in j.reason


def test_case24_near_40_without_history_lowers():
    assert judge(200, 79, past_weeks=[]).verdict == "하향"
    assert judge(200, 79, past_weeks=None).verdict == "하향"


def test_case25_near_60_with_past_week_at_or_above_60_raises():
    j = judge(200, 119, past_weeks=[(50, 31)])  # 과거 62%
    assert j.verdict == "상향" and "60%로 보정" in j.reason


def test_correction_only_within_one_percentage_point():
    # 38.5%는 1%p를 넘게 모자라서 과거 기록이 있어도 보정하지 않는다
    assert judge(200, 77, past_weeks=[(100, 45)]).verdict == "하향"
    # 58.5%도 마찬가지
    assert judge(200, 117, past_weeks=[(50, 31)]).verdict == "유지"


def test_past_week_must_reach_the_boundary_to_correct():
    # 과거가 35%였다면 40% 기준을 넘은 적이 없으므로 39.5%는 하향
    assert judge(200, 79, past_weeks=[(100, 35)]).verdict == "하향"
    # 40% 기록은 60% 경계 보정 근거가 되지 못한다
    assert judge(200, 119, past_weeks=[(100, 45)]).verdict == "유지"


def test_past_week_under_20_attempts_does_not_count():
    assert judge(200, 79, past_weeks=[(10, 9)]).verdict == "하향"


def test_rounding_to_one_decimal():
    # 2000회 중 799회 = 39.95% -> 반올림 40.0% -> 유지 (과거 기록 없이도)
    j = judge(2000, 799)
    assert (j.verdict, j.rate) == ("유지", 40.0)
    # 2000회 중 798회 = 39.9% -> 하향
    assert judge(2000, 798).verdict == "하향"


@pytest.mark.parametrize("attempts,makes", [(10, 11), (-1, 0), (5, -1)])
def test_invalid_counts_raise(attempts, makes):
    with pytest.raises(ValueError):
        judge(attempts, makes)
