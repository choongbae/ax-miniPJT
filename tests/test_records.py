from datetime import date

import pytest

from src.models import WeeklyPlan
from src.records import (
    RecordStore,
    judge_week,
    previous_week_keys,
    validate_rating,
    validate_shot_record,
    week_key,
)
from src.tools import load_drills

CATALOG = load_drills()
WEEK = "2026-W46"


def one_drill_plan(*names):
    drills = [{"name": n, "sets": 4, "reps": 10, "minutes": 20, "purpose": "p"} for n in names]
    return WeeklyPlan.model_validate({"days": [{"day": "월", "drills": drills}]})


def test_week_key_starts_on_monday():
    assert week_key(date(2026, 11, 9)) == "2026-W46"  # 월요일
    assert week_key(date(2026, 11, 15)) == "2026-W46"  # 일요일
    assert week_key(date(2026, 11, 16)) == "2026-W47"


def test_previous_week_keys_cross_year_boundary():
    assert previous_week_keys("2026-W02", 4) == ["2026-W01", "2025-W52", "2025-W51", "2025-W50"]


def test_case16_makes_greater_than_attempts_is_rejected():
    errors = validate_shot_record(20, 25)
    assert errors == ["성공 수(25)가 시도 수(20)보다 많을 수 없습니다."]


@pytest.mark.parametrize("attempts,makes", [(0, 0), (-5, 0), (10, -1), ("많이", 3), (10, "조금")])
def test_invalid_shot_records(attempts, makes):
    assert validate_shot_record(attempts, makes)


def test_valid_shot_record_has_no_errors():
    assert validate_shot_record(50, 10) == []
    assert validate_shot_record("50", "10") == []  # CLI에서 문자열로 들어온 경우


def test_rating_validation():
    assert validate_rating("적당") == []
    assert validate_rating("보통")


def test_invalid_record_is_not_saved(tmp_path):
    store = RecordStore(tmp_path / "r.json")
    assert store.add_shot("u", "3점 캐치앤슛", WEEK, 20, 25)  # 오류 안내가 나온다
    assert not store.has_records("u")
    assert not (tmp_path / "r.json").exists()


def test_records_persist_and_reload(tmp_path):
    path = tmp_path / "r.json"
    store = RecordStore(path)
    assert store.add_shot("u", "3점 캐치앤슛", WEEK, 50, 10) == []
    assert store.add_rating("u", "양손 레이업", WEEK, "쉬웠음") == []
    reloaded = RecordStore(path)
    assert reloaded.shots("u", "3점 캐치앤슛", WEEK) == [(50, 10)]
    assert reloaded.ratings("u", "양손 레이업", WEEK) == ["쉬웠음"]


def test_users_do_not_see_each_others_records(tmp_path):
    store = RecordStore(tmp_path / "r.json")
    store.add_shot("a", "3점 캐치앤슛", WEEK, 50, 10)
    assert store.has_records("a") and not store.has_records("b")
    assert store.shots("b", "3점 캐치앤슛", WEEK) == []


def test_past_weeks_returns_weekly_sums_of_last_four_weeks(tmp_path):
    store = RecordStore(tmp_path / "r.json")
    store.add_shot("u", "3점 캐치앤슛", "2026-W45", 50, 20)
    store.add_shot("u", "3점 캐치앤슛", "2026-W45", 50, 25)  # 같은 주 두 번 -> 합산
    store.add_shot("u", "3점 캐치앤슛", "2026-W42", 40, 10)
    store.add_shot("u", "3점 캐치앤슛", "2026-W41", 40, 30)  # 5주 전 -> 제외
    store.add_shot("u", "3점 캐치앤슛", WEEK, 40, 30)  # 이번 주 -> 제외
    assert store.past_weeks("u", "3점 캐치앤슛", WEEK) == [(100, 45), (40, 10)]


def test_judge_week_uses_records_and_flags_missing_ones(tmp_path):
    store = RecordStore(tmp_path / "r.json")
    store.add_shot("u", "3점 캐치앤슛", WEEK, 50, 10)  # 20% -> 하향
    plan = one_drill_plan("3점 캐치앤슛", "양손 레이업")
    result = {j.drill: j for j in judge_week(store, "u", WEEK, plan, CATALOG)}
    assert result["3점 캐치앤슛"].verdict == "하향"
    assert result["양손 레이업"].carry_over is True  # 기록이 없음 -> 다음 주에 다시 넣는다


def test_judge_week_applies_past_week_correction(tmp_path):
    store = RecordStore(tmp_path / "r.json")
    store.add_shot("u", "3점 캐치앤슛", "2026-W44", 100, 45)  # 과거 45%
    store.add_shot("u", "3점 캐치앤슛", WEEK, 200, 79)  # 39.5%
    plan = one_drill_plan("3점 캐치앤슛")
    assert judge_week(store, "u", WEEK, plan, CATALOG)[0].verdict == "유지"


def test_concurrent_writes_do_not_corrupt_the_file(tmp_path):
    """API가 요청을 동시에 처리해도 기록이 빠지거나 파일이 깨지지 않는다."""
    import json
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "r.json"
    store = RecordStore(path)

    def write(i):
        store.add_shot(f"user{i % 4}", "3점 캐치앤슛", WEEK, 20 + i, i % 10)
        store.add_rating(f"user{i % 4}", "양손 레이업", WEEK, "적당")

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(write, range(80)))

    saved = json.loads(path.read_text(encoding="utf-8"))  # 깨졌다면 여기서 오류가 난다
    assert len(saved) == 160
    assert len(RecordStore(path)._entries) == 160
