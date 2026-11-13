"""같은 메뉴가 여러 요일에 있을 때 카드마다 따로 기록 (T41-1). 기본 가짜 계획은 월·화·수 3일에 '제자리 볼 핸들링'과 '제자리 한 손 드리블'이 있다."""
import sqlite3

import pytest

from src.models import WeeklyPlan
from src.records import RecordStore, plan_slots
from src.store import SqliteStore
from tests.test_web import FORM, env, make_plan, plan_with, signup, user  # noqa: F401

DRILL = "제자리 볼 핸들링"


def save(c, slot, rating, drill=DRILL, week=None):
    body = {"drill": drill, "ratings": [rating], "slot": slot}
    if week:
        body["week"] = week
    return c.post("/records", json=body)


def cards(c, drill=DRILL, week=None):
    rows = c.get("/records/week", params={"week": week} if week else None).json()
    return {r["slot"]: r for r in rows if r["drill"] == drill}


# --- 슬롯 나누기 ------------------------------------------------------------------------------

def test_slots_are_the_day_and_a_number_when_the_same_drill_repeats_in_a_day():
    plan = WeeklyPlan.model_validate({"days": [
        {"day": "월", "drills": [{"name": "벽 패스", "sets": 3, "reps": 10, "minutes": 5, "purpose": "p"}, {"name": "벽 패스", "sets": 3, "reps": 10, "minutes": 5, "purpose": "p"}, {"name": "피벗 연습", "sets": 3, "reps": 10, "minutes": 5, "purpose": "p"}]},
        {"day": "수", "drills": [{"name": "벽 패스", "sets": 3, "reps": 10, "minutes": 5, "purpose": "p"}]},
    ]})
    assert plan_slots(plan) == [("벽 패스", "월"), ("벽 패스", "월#2"), ("피벗 연습", "월"), ("벽 패스", "수")]


# --- 카드마다 다른 값 -------------------------------------------------------------------------

def test_each_card_of_the_same_drill_keeps_its_own_value(user, env):
    make_plan(user, FORM)
    plan = user.get("/plans/current").json()
    assert [d["slot"] for day in plan["days"] for d in day["drills"] if d["name"] == DRILL] == ["월", "화", "수"]  # 카드마다 슬롯을 준다
    for slot, rating in (("월", "적당"), ("화", "쉬웠음"), ("수", "어려웠음")):
        assert save(user, slot, rating).status_code == 200
    got = cards(user)
    assert {s: r["ratings"] for s, r in got.items()} == {"월": ["적당"], "화": ["쉬웠음"], "수": ["어려웠음"]}
    assert [r["day"] for r in got.values()] == ["월", "화", "수"]
    assert env.store.count_week_records("minsu", "2026-W46") == 3  # 카드마다 한 건


def test_updating_one_card_leaves_the_others_alone_and_never_piles_up(user, env):
    make_plan(user, FORM)
    for slot, rating in (("월", "적당"), ("화", "쉬웠음")):
        save(user, slot, rating)
    save(user, "화", "어려웠음")  # 화요일 카드만 갱신
    assert {s: r["ratings"] for s, r in cards(user).items()} == {"월": ["적당"], "화": ["어려웠음"], "수": []}
    assert env.store.count_week_records("minsu", "2026-W46") == 2


def test_a_shot_card_per_day_also_works(env):
    env.gen.plan_fn = lambda u, v, j: WeeklyPlan.model_validate({"days": [
        {"day": d, "drills": [{"name": "3점 캐치앤슛", "sets": 3, "reps": 10, "minutes": 10, "purpose": "p"}]} for d in ("월", "목")]})
    signup(env.c)
    make_plan(env.c, FORM)
    env.c.post("/records", json={"drill": "3점 캐치앤슛", "shots": [{"attempts": 20, "makes": 5}], "slot": "월"})
    env.c.post("/records", json={"drill": "3점 캐치앤슛", "shots": [{"attempts": 30, "makes": 12}], "slot": "목"})
    got = cards(env.c, "3점 캐치앤슛")
    assert got["월"]["shots"] == [{"attempts": 20, "makes": 5}] and got["목"]["shots"] == [{"attempts": 30, "makes": 12}]


# --- 난이도 판정은 모든 카드를 합쳐서 -----------------------------------------------------------

def test_the_difficulty_judgment_combines_all_cards_of_the_drill(user):
    make_plan(user, FORM)
    for slot, rating in (("월", "쉬웠음"), ("화", "쉬웠음"), ("수", "적당")):
        save(user, slot, rating)
    verdicts = {r["verdict"] for r in cards(user).values()}
    assert verdicts == {"상향"}  # 가장 많은 평가가 쉬웠음 (모든 카드가 같은 종합 판정)


def test_three_different_ratings_tie_and_keep(user):
    make_plan(user, FORM)
    for slot, rating in (("월", "쉬웠음"), ("화", "적당"), ("수", "어려웠음")):
        save(user, slot, rating)
    rows = cards(user).values()
    assert {r["verdict"] for r in rows} == {"유지"} and all("동수" in r["reason"] for r in rows)


def test_shots_of_the_cards_add_up_for_the_judgment(env):
    env.gen.plan_fn = lambda u, v, j: WeeklyPlan.model_validate({"days": [
        {"day": d, "drills": [{"name": "3점 캐치앤슛", "sets": 3, "reps": 10, "minutes": 10, "purpose": "p"}]} for d in ("월", "목")]})
    signup(env.c)
    make_plan(env.c, FORM)
    env.c.post("/records", json={"drill": "3점 캐치앤슛", "shots": [{"attempts": 50, "makes": 10}], "slot": "월"})
    env.c.post("/records", json={"drill": "3점 캐치앤슛", "shots": [{"attempts": 50, "makes": 30}], "slot": "목"})
    row = cards(env.c, "3점 캐치앤슛")["월"]
    assert row["verdict"] == "유지" and "40.0%" in row["reason"]  # 평가 세트 케이스 2와 같은 합산 (100회 중 40회)


def test_the_progress_screen_sums_the_cards(user):
    make_plan(user, FORM)
    for slot, rating in (("월", "쉬웠음"), ("화", "적당")):
        save(user, slot, rating)
    row = next(f for f in user.get("/progress").json()["fields"] if f["field"] == "드리블")["weeks"][-1]
    assert row["rating_count"] == 2 and row["rating_avg"] == 2.5


# --- 슬롯 검사 --------------------------------------------------------------------------------

@pytest.mark.parametrize("slot", ["목", "월#2", "x", "월요일", "", "토#1"])
def test_a_slot_that_is_not_a_card_of_this_drill_is_rejected(user, slot):
    make_plan(user, FORM)  # 월·화·수에 카드가 있다
    r = save(user, slot, "적당")
    if slot == "":
        assert r.status_code == 200  # 빈 슬롯은 슬롯 없음과 같다(이전 방식)
    else:
        assert r.status_code == 422


def test_the_slot_must_belong_to_the_drill_in_the_plan(user):
    make_plan(user, FORM)
    assert save(user, "월", "적당", drill="양손 레이업").status_code == 422  # 이 계획에 없는 메뉴의 카드


def test_a_slot_is_accepted_when_there_is_no_plan_yet(user):
    assert save(user, "월", "적당", week="2026-W44").status_code == 200


def test_the_same_drill_twice_in_one_day_has_two_cards(user, env):
    env.gen.plan_fn = lambda u, v, j: WeeklyPlan.model_validate({"days": [
        {"day": "월", "drills": [{"name": DRILL, "sets": 3, "reps": 10, "minutes": 10, "purpose": "p"}, {"name": DRILL, "sets": 3, "reps": 10, "minutes": 10, "purpose": "p"}]}]})
    make_plan(user, FORM)
    save(user, "월", "적당")
    save(user, "월#2", "쉬웠음")
    assert {s: r["ratings"] for s, r in cards(user).items()} == {"월": ["적당"], "월#2": ["쉬웠음"]}


# --- 예전 기록과 슬롯 없는 저장 ------------------------------------------------------------------

def test_older_records_without_a_slot_show_on_the_first_card_and_saving_it_replaces_them(user, env):
    make_plan(user, FORM)
    env.store.add_rating("minsu", DRILL, "2026-W46", "쉬웠음")
    env.store.add_rating("minsu", DRILL, "2026-W46", "적당")  # 예전 방식: 슬롯 없이 여러 건
    got = cards(user)
    assert got["월"]["ratings"] == ["쉬웠음", "적당"] and got["화"]["ratings"] == [] and got["수"]["ratings"] == []
    save(user, "화", "어려웠음")  # 첫 카드가 아니면 예전 기록을 건드리지 않는다
    assert cards(user)["월"]["ratings"] == ["쉬웠음", "적당"]
    save(user, "월", "쉬웠음")  # 첫 카드를 저장하면 예전 기록이 한 건으로 바뀐다
    assert {s: r["ratings"] for s, r in cards(user).items()} == {"월": ["쉬웠음"], "화": ["어려웠음"], "수": []}


def test_saving_without_a_slot_replaces_every_card_of_the_drill_for_the_week(user, env):
    make_plan(user, FORM)
    save(user, "월", "적당")
    save(user, "화", "쉬웠음")
    assert user.post("/records", json={"drill": DRILL, "ratings": ["어려웠음"]}).status_code == 200  # 이전 방식(슬롯 없음)
    got = cards(user)
    assert got["월"]["ratings"] == ["어려웠음"] and got["화"]["ratings"] == [] and got["수"]["ratings"] == []
    assert env.store.count_week_records("minsu", "2026-W46") == 1


def test_deleting_the_plan_or_regenerating_still_clears_every_card(user, env):
    make_plan(user, FORM)
    for slot in ("월", "화", "수"):
        save(user, slot, "적당")
    assert user.delete("/plans", params={"week": "2026-W46"}).json()["deleted_records"] == 3


# --- 저장소 ------------------------------------------------------------------------------------

@pytest.fixture(params=["json", "sqlite"])
def store(request, tmp_path):
    return RecordStore(tmp_path / "r.json") if request.param == "json" else SqliteStore(tmp_path / "r.db")


def test_stores_replace_only_the_given_card(store):
    store.replace_record("u", DRILL, "2026-W46", rating="적당", slot="월")
    store.replace_record("u", DRILL, "2026-W46", rating="쉬웠음", slot="화")
    store.replace_record("u", DRILL, "2026-W46", rating="어려웠음", slot="월")
    got = store.slot_records("u", "2026-W46")[DRILL]
    assert got["월"]["ratings"] == ["어려웠음"] and got["화"]["ratings"] == ["쉬웠음"]
    assert sorted(store.ratings("u", DRILL, "2026-W46")) == ["쉬웠음", "어려웠음"]  # 메뉴 단위 조회는 모든 카드를 합친다


def test_stores_keep_the_legacy_slot_unless_asked_to_absorb_it(store):
    store.add_rating("u", DRILL, "2026-W46", "쉬웠음")  # 슬롯 없음
    store.replace_record("u", DRILL, "2026-W46", rating="적당", slot="화")
    assert store.slot_records("u", "2026-W46")[DRILL][""]["ratings"] == ["쉬웠음"]
    store.replace_record("u", DRILL, "2026-W46", rating="어려웠음", slot="월", absorb_legacy=True)
    assert "" not in store.slot_records("u", "2026-W46")[DRILL]


def test_an_older_sqlite_database_without_the_slot_column_is_upgraded(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(
        "CREATE TABLE shot_records (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, drill TEXT NOT NULL, week TEXT NOT NULL, attempts INTEGER NOT NULL, makes INTEGER NOT NULL);"
        "CREATE TABLE rating_records (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, drill TEXT NOT NULL, week TEXT NOT NULL, rating TEXT NOT NULL);"
        "INSERT INTO shot_records (user_id, drill, week, attempts, makes) VALUES ('u', '3점 캐치앤슛', '2026-W45', 50, 20);"
        "INSERT INTO rating_records (user_id, drill, week, rating) VALUES ('u', '양손 레이업', '2026-W45', '적당');"
    )
    con.commit()
    con.close()
    s = SqliteStore(path)  # 열 때 슬롯 열을 더한다
    got = s.slot_records("u", "2026-W45")
    assert got["3점 캐치앤슛"][""]["shots"] == [(50, 20)] and got["양손 레이업"][""]["ratings"] == ["적당"]  # 예전 기록은 슬롯 ''
    s.replace_record("u", "양손 레이업", "2026-W45", rating="쉬웠음", slot="월", absorb_legacy=True)
    assert s.ratings("u", "양손 레이업", "2026-W45") == ["쉬웠음"]
