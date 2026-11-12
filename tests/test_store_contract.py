"""JSON 저장소(RecordStore)와 SQLite 저장소(SqliteStore)가 같은 동작을 하는지 확인한다 (T25)."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.models import WeeklyPlan
from src.records import RecordStore, judge_week
from src.store import SqliteStore
from src.tools import load_drills

CATALOG = load_drills()
WEEK = "2026-W46"


def make_store(kind, path):
    return RecordStore(path / "r.json") if kind == "json" else SqliteStore(path / "r.db")


@pytest.fixture(params=["json", "sqlite"])
def kind(request):
    return request.param


@pytest.fixture
def store(kind, tmp_path):
    return make_store(kind, tmp_path)


def plan_of(*names):
    drills = [{"name": n, "sets": 3, "reps": 10, "minutes": 10, "purpose": "p"} for n in names]
    return WeeklyPlan.model_validate({"days": [{"day": "월", "drills": drills}]})


def test_invalid_shot_is_not_saved(store):
    assert store.add_shot("u", "3점 캐치앤슛", WEEK, 20, 25) == ["성공 수(25)가 시도 수(20)보다 많을 수 없습니다."]
    assert store.add_rating("u", "양손 레이업", WEEK, "보통") == ["자기평가는 쉬웠음, 적당, 어려웠음 중 하나여야 합니다."]
    assert not store.has_records("u")


def test_records_are_returned_in_order(store):
    store.add_shot("u", "3점 캐치앤슛", WEEK, 50, 10)
    store.add_shot("u", "3점 캐치앤슛", WEEK, 50, 30)
    store.add_rating("u", "양손 레이업", WEEK, "쉬웠음")
    store.add_rating("u", "양손 레이업", WEEK, "적당")
    assert store.shots("u", "3점 캐치앤슛", WEEK) == [(50, 10), (50, 30)]
    assert store.ratings("u", "양손 레이업", WEEK) == ["쉬웠음", "적당"]
    assert store.shots("u", "3점 캐치앤슛", "2026-W45") == []
    assert store.ratings("u", "3점 캐치앤슛", WEEK) == []


def test_users_never_see_each_others_records(store):
    store.add_shot("a", "3점 캐치앤슛", WEEK, 50, 10)
    store.add_rating("a", "양손 레이업", WEEK, "쉬웠음")
    store.save_plan("a", WEEK, plan_of("3점 캐치앤슛"))
    assert store.has_records("a") and not store.has_records("b")
    assert store.shots("b", "3점 캐치앤슛", WEEK) == [] and store.ratings("b", "양손 레이업", WEEK) == []
    assert store.get_plan("b", WEEK) is None


def test_records_survive_reopening(kind, tmp_path):
    store = make_store(kind, tmp_path)
    store.add_shot("u", "3점 캐치앤슛", WEEK, 50, 10)
    store.save_plan("u", WEEK, plan_of("3점 캐치앤슛", "풀업 점퍼"))
    again = make_store(kind, tmp_path)
    assert again.shots("u", "3점 캐치앤슛", WEEK) == [(50, 10)]
    assert [d.name for d in again.get_plan("u", WEEK).days[0].drills] == ["3점 캐치앤슛", "풀업 점퍼"]


def test_past_weeks_sums_each_of_the_last_four_weeks(store):
    store.add_shot("u", "3점 캐치앤슛", "2026-W45", 50, 20)
    store.add_shot("u", "3점 캐치앤슛", "2026-W45", 50, 25)
    store.add_shot("u", "3점 캐치앤슛", "2026-W42", 40, 10)
    store.add_shot("u", "3점 캐치앤슛", "2026-W41", 40, 30)  # 5주 전
    store.add_shot("u", "3점 캐치앤슛", WEEK, 40, 30)  # 이번 주
    assert store.past_weeks("u", "3점 캐치앤슛", WEEK) == [(100, 45), (40, 10)]


def test_plan_is_replaced_within_the_same_week(store):
    store.save_plan("u", WEEK, plan_of("3점 캐치앤슛"))
    store.save_plan("u", WEEK, plan_of("풀업 점퍼"))
    assert [d.name for d in store.get_plan("u", WEEK).days[0].drills] == ["풀업 점퍼"]
    assert store.get_plan("u", "2026-W47") is None


def test_plan_entries_do_not_break_record_lookups(store):
    store.save_plan("me", WEEK, plan_of("3점 캐치앤슛"))
    assert store.shots("me", "3점 캐치앤슛", WEEK) == [] and store.ratings("me", "3점 캐치앤슛", WEEK) == []
    assert store.past_weeks("me", "3점 캐치앤슛", "2026-W47") == []
    assert store.has_records("me") and store.user_ids() == ["me"]


def test_judge_week_works_with_either_store(store):
    store.add_shot("u", "3점 캐치앤슛", WEEK, 50, 10)
    result = {j.drill: j for j in judge_week(store, "u", WEEK, plan_of("3점 캐치앤슛", "양손 레이업"), CATALOG)}
    assert result["3점 캐치앤슛"].verdict == "하향" and result["양손 레이업"].carry_over is True


def test_user_ids_lists_everyone_with_data(store):
    store.add_shot("b", "3점 캐치앤슛", WEEK, 50, 10)
    store.add_rating("a", "양손 레이업", WEEK, "적당")
    store.save_plan("c", WEEK, plan_of("3점 캐치앤슛"))
    assert store.user_ids() == ["a", "b", "c"]


def test_hostile_strings_are_stored_literally(store):
    """SQL이나 JSON을 깨려는 문자열도 그냥 값으로 저장되고 다른 데이터에 영향을 주지 않는다."""
    nasty = "x'); DROP TABLE users; --"
    store.add_shot(nasty, nasty, WEEK, 50, 10)
    store.add_shot("safe", "3점 캐치앤슛", WEEK, 50, 20)
    assert store.shots(nasty, nasty, WEEK) == [(50, 10)]
    assert store.shots("safe", "3점 캐치앤슛", WEEK) == [(50, 20)]
    assert nasty in store.user_ids()


def test_concurrent_writes_do_not_lose_or_corrupt_data(kind, tmp_path):
    store = make_store(kind, tmp_path)

    def write(i):
        store.add_shot(f"user{i % 4}", "3점 캐치앤슛", WEEK, 20 + i, i % 10)
        store.add_rating(f"user{i % 4}", "양손 레이업", WEEK, "적당")

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(write, range(80)))

    again = make_store(kind, tmp_path)  # 파일이 깨졌다면 여기서 오류가 난다
    total_shots = sum(len(again.shots(f"user{u}", "3점 캐치앤슛", WEEK)) for u in range(4))
    total_ratings = sum(len(again.ratings(f"user{u}", "양손 레이업", WEEK)) for u in range(4))
    assert (total_shots, total_ratings) == (80, 80)
    if kind == "json":
        assert len(json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))) == 160


# --- SQLite 전용: 계정과 세션 -----------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    return SqliteStore(tmp_path / "app.db")


def test_create_user_is_unique_ignoring_case(db):
    assert db.create_user("Minsu", "h", "s", "2026-11-12T00:00:00Z") is True
    assert db.create_user("minsu", "h2", "s2", "2026-11-12T00:00:00Z") is False
    assert db.create_user("MINSU", "h3", "s3", "2026-11-12T00:00:00Z") is False
    assert db.get_user("MINSU")["username"] == "Minsu"  # 처음 만든 표기를 그대로 돌려준다


def test_get_user_for_unknown_name_is_none(db):
    assert db.get_user("nobody") is None


def test_session_lifecycle(db):
    db.create_user("minsu", "h", "s", "2026-11-12T00:00:00Z")
    db.create_session("tokenhash", "minsu", "2026-11-19T00:00:00Z")
    assert db.find_session("tokenhash", "2026-11-12T00:00:00Z") == "minsu"
    assert db.find_session("tokenhash", "2026-11-19T00:00:00Z") is None  # 만료 시각이 되면 끝난다
    assert db.find_session("tokenhash", "2026-11-12T00:00:00Z") is None  # 만료된 세션은 지워졌다


def test_deleted_session_is_gone_and_unknown_hash_is_none(db):
    db.create_user("minsu", "h", "s", "2026-11-12T00:00:00Z")
    db.create_session("tokenhash", "minsu", "2026-11-19T00:00:00Z")
    db.delete_session("tokenhash")
    assert db.find_session("tokenhash", "2026-11-12T00:00:00Z") is None
    assert db.find_session("never-existed", "2026-11-12T00:00:00Z") is None


def test_session_requires_an_existing_user(db):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        db.create_session("tokenhash", "ghost", "2026-11-19T00:00:00Z")


def test_user_ids_includes_accounts_without_records(db):
    db.create_user("minsu", "h", "s", "2026-11-12T00:00:00Z")
    assert db.user_ids() == ["minsu"]


# --- 주 기록 초기화 (T35) ---------------------------------------------------------------------

def test_delete_week_records_removes_only_that_users_records_of_that_week(store):
    store.add_shot("u", "3점 캐치앤슛", WEEK, 20, 10)
    store.add_shot("u", "3점 캐치앤슛", WEEK, 10, 5)
    store.add_rating("u", "양손 레이업", WEEK, "쉬웠음")
    store.add_shot("u", "3점 캐치앤슛", "2026-W45", 30, 15)  # 다른 주
    store.add_shot("v", "3점 캐치앤슛", WEEK, 30, 15)  # 다른 사용자
    store.save_plan("u", WEEK, plan_of("3점 캐치앤슛"))
    assert store.count_week_records("u", WEEK) == 3  # 계획은 세지 않는다
    assert store.delete_week_records("u", WEEK) == 3
    assert store.count_week_records("u", WEEK) == 0
    assert store.shots("u", "3점 캐치앤슛", WEEK) == [] and store.ratings("u", "양손 레이업", WEEK) == []
    assert store.shots("u", "3점 캐치앤슛", "2026-W45") == [(30, 15)] and store.shots("v", "3점 캐치앤슛", WEEK) == [(30, 15)]
    assert store.get_plan("u", WEEK) is not None  # 계획은 그대로
    assert store.delete_week_records("u", WEEK) == 0  # 지울 것이 없으면 0


def test_deleted_records_no_longer_count_for_the_next_weeks_judgment(store):
    store.add_shot("u", "3점 캐치앤슛", WEEK, 50, 40)
    store.save_plan("u", WEEK, plan_of("3점 캐치앤슛"))
    before = judge_week(store, "u", WEEK, plan_of("3점 캐치앤슛"), CATALOG)[0]
    assert before.verdict == "상향" and not before.carry_over
    store.delete_week_records("u", WEEK)
    after = judge_week(store, "u", WEEK, plan_of("3점 캐치앤슛"), CATALOG)[0]
    assert after.carry_over is True and after.verdict == "유지"



def test_records_for_weeks_returns_all_records_of_the_wanted_weeks_in_one_call(store):
    store.add_shot("u", "3점 캐치앤슛", WEEK, 20, 10)
    store.add_shot("u", "3점 캐치앤슛", WEEK, 10, 5)
    store.add_rating("u", "양손 레이업", WEEK, "쉬웠음")
    store.add_rating("u", "양손 레이업", "2026-W45", "어려웠음")
    store.add_shot("u", "3점 캐치앤슛", "2026-W40", 30, 15)  # 원하지 않는 주
    store.add_shot("v", "3점 캐치앤슛", WEEK, 99, 9)  # 다른 사용자
    store.save_plan("u", WEEK, plan_of("3점 캐치앤슛"))  # 계획은 기록이 아니다
    got = store.records_for_weeks("u", [WEEK, "2026-W45"])
    assert got[WEEK]["3점 캐치앤슛"] == {"shots": [(20, 10), (10, 5)], "ratings": []}
    assert got[WEEK]["양손 레이업"] == {"shots": [], "ratings": ["쉬웠음"]}
    assert got["2026-W45"]["양손 레이업"]["ratings"] == ["어려웠음"]
    assert "2026-W40" not in got and store.records_for_weeks("u", []) == {}
