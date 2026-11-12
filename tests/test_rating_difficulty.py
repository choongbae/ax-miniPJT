import pytest

from src.tools import judge_rating_difficulty as judge


def test_case5_mostly_easy_raises():
    # 케이스 5: 쉬웠음 2번, 적당 1번
    j = judge(["쉬웠음", "쉬웠음", "적당"])
    assert j.verdict == "상향" and "쉬웠음" in j.reason


def test_mostly_fine_keeps():
    assert judge(["적당", "적당", "어려웠음"]).verdict == "유지"


def test_mostly_hard_lowers():
    assert judge(["어려웠음", "어려웠음", "쉬웠음"]).verdict == "하향"


def test_case14_three_way_tie_keeps():
    j = judge(["쉬웠음", "적당", "어려웠음"])
    assert j.verdict == "유지" and "동수" in j.reason


def test_two_way_tie_between_easy_and_hard_keeps():
    assert judge(["쉬웠음", "어려웠음"]).verdict == "유지"


def test_single_record():
    assert judge(["쉬웠음"]).verdict == "상향"
    assert judge(["어려웠음"]).verdict == "하향"


def test_no_ratings_keeps():
    assert judge([]).verdict == "유지"


def test_does_not_use_shot_rate():
    assert judge(["쉬웠음"]).rate is None


def test_unknown_rating_raises():
    with pytest.raises(ValueError):
        judge(["보통"])
