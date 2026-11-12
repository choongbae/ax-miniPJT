"""계획 재생성 시 수행 기록 초기화 (T35): 이미 계획이 있는 주를 다시 만들어 확정하면 그 주의 기록이 지워진다."""
from fastapi.testclient import TestClient

from tests.test_web import FORM, SHOT_BODY, env, make_plan, plan_with, signup, user  # noqa: F401

PAST = "2026-W44"


def pending(c, **change):
    r = c.post("/plans", json={**FORM, **change}).json()
    assert r["status"] == "pending", r
    return r


def decide(c, draft, decision="confirm"):
    return c.post(f"/plans/{draft['plan_id']}/decision", json={"decision": decision}).json()


def record_some(c, week=None):
    extra = {"week": week} if week else {}
    assert c.post("/records", json={**SHOT_BODY, **extra}).status_code == 200  # 슛 한 건
    assert c.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["쉬웠음", "적당"], **extra}).status_code == 200  # 평가 두 건
    return 3


def week_rows(c, week=None):
    return {r["drill"]: r for r in c.get("/records/week", params={"week": week} if week else None).json()}


def test_the_first_plan_of_a_week_resets_nothing(user):
    d = pending(user)
    assert d["resets_records"] == 0
    assert decide(user, d)["resets_records"] == 0


def test_regenerating_a_week_with_records_warns_then_resets_them_on_confirm(user, env):
    decide(user, pending(user))
    n = record_some(user)
    d = pending(user, goals=["레이업"])
    assert d["resets_records"] == n  # 확정하기 전에 지워질 건수를 알려 준다
    assert env.store.count_week_records("minsu", "2026-W46") == n  # 아직 지워지지 않았다
    done = decide(user, d)
    assert done["status"] == "confirmed" and done["resets_records"] == n
    assert env.store.count_week_records("minsu", "2026-W46") == 0
    rows = week_rows(user)
    assert all(r["shots"] == [] and r["ratings"] == [] and r["carry_over"] for r in rows.values())  # 다음 주 난이도 예고도 '기록 없음'으로


def test_rejecting_or_leaving_a_draft_keeps_the_records(user, env):
    decide(user, pending(user))
    n = record_some(user)
    decide(user, pending(user), "reject")
    assert env.store.count_week_records("minsu", "2026-W46") == n
    pending(user)  # 확정도 거절도 안 한 초안
    assert env.store.count_week_records("minsu", "2026-W46") == n


def test_records_of_other_weeks_and_other_users_are_kept(user, env):
    make_plan(user, {**FORM, "week": PAST})
    record_some(user, PAST)
    decide(user, pending(user))
    record_some(user)
    other = TestClient(env.app)
    signup(other, "jisu")
    make_plan(other, FORM)
    record_some(other)
    decide(user, pending(user, goals=["패스"]))  # 이번 주만 다시 만든다
    assert env.store.count_week_records("minsu", "2026-W46") == 0
    assert env.store.count_week_records("minsu", PAST) == 3
    assert env.store.count_week_records("jisu", "2026-W46") == 3


def test_regenerating_a_past_week_resets_that_week_too(user, env):
    make_plan(user, {**FORM, "week": PAST})
    record_some(user, PAST)
    d = pending(user, week=PAST)
    assert d["resets_records"] == 3
    decide(user, d)
    assert env.store.count_week_records("minsu", PAST) == 0


def test_records_entered_before_any_plan_exists_are_not_wiped_by_the_first_plan(user, env):
    record_some(user, PAST)  # 계획 없이 과거 기록을 먼저 채워 넣었다
    d = pending(user, week=PAST)
    assert d["resets_records"] == 0
    assert decide(user, d)["resets_records"] == 0
    assert env.store.count_week_records("minsu", PAST) == 3


def test_the_next_weeks_difficulty_stops_using_the_reset_records(user, env):
    make_plan(user, {**FORM, "week": PAST})
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["쉬웠음", "쉬웠음"], "week": PAST})
    env.gen.plan_fn = lambda u, v, j: plan_with("제자리 한 손 드리블", "양손 크로스오버 드리블")  # 상향된 볼 핸들링은 빼고 계획
    first = make_plan(user, {**FORM, "week": "2026-W45", "equipment": [], "days_per_week": 1, "level": "초급"}).json()["plan"]["last_week"]
    assert {j["drill"]: j["verdict"] for j in first}["제자리 볼 핸들링"] == "상향"
    env.gen.plan_fn = None  # 기본 계획(볼 핸들링, 한 손 드리블)
    decide(user, pending(user, week=PAST))  # W44를 다시 만들어 기록을 지운다
    second = make_plan(user, {**FORM, "week": "2026-W45"}).json()["plan"]["last_week"]
    assert all(j["carry_over"] for j in second)  # 지워진 기록은 더는 W45 계획에 쓰이지 않는다
