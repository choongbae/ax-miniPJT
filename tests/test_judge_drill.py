from src.agent import build_prompt_values
from src.models import Drill, UserInput
from src.tools import judge_drill, load_drills

CATALOG = {d.name: d for d in load_drills()}
SHOT = CATALOG["3점 캐치앤슛"]
LAYUP = CATALOG["양손 레이업"]


def test_case10_no_record_keeps_and_is_carried_over():
    # 케이스 10: 레이업을 한 번도 기록하지 못했다
    j = judge_drill(LAYUP)
    assert j.verdict == "유지" and j.carry_over is True
    assert "다시 넣습니다" in j.reason


def test_shot_drill_with_no_attempts_is_no_record():
    assert judge_drill(SHOT, shots=[]).carry_over is True
    assert judge_drill(SHOT, shots=[(0, 0)]).carry_over is True


def test_rating_drill_with_empty_ratings_is_no_record():
    assert judge_drill(LAYUP, ratings=[]).carry_over is True


def test_shot_drill_sums_sessions_for_the_week():
    # 케이스 2: 월 50회 중 10회 + 목 50회 중 30회
    j = judge_drill(SHOT, shots=[(50, 10), (50, 30)])
    assert j.verdict == "유지" and j.carry_over is False


def test_shot_drill_uses_past_weeks_for_boundary_correction():
    j = judge_drill(SHOT, shots=[(200, 79)], past_weeks=[(100, 45)])
    assert j.verdict == "유지"
    assert judge_drill(SHOT, shots=[(200, 79)]).verdict == "하향"


def test_non_shot_drill_uses_ratings_not_shots():
    j = judge_drill(LAYUP, shots=[(50, 10)], ratings=["쉬웠음", "쉬웠음", "적당"])
    assert j.verdict == "상향"


def test_few_shots_keep_but_are_not_carried_over():
    # 기록은 있었으므로 '기록 없음'이 아니다 (표본 부족으로 유지)
    j = judge_drill(SHOT, shots=[(15, 3)])
    assert j.verdict == "유지" and j.carry_over is False


def test_case6_first_plan_level_follows_entered_level():
    # 케이스 6: 지난 기록이 없는 첫 사용자의 첫 계획 난이도는 입력한 수준 그대로
    user = UserInput(position="가드", level="초급", goals=[], days_per_week=2, minutes_per_session=30, equipment=[])
    values = build_prompt_values(user, list(CATALOG.values()))
    assert values["level"] == "초급"
