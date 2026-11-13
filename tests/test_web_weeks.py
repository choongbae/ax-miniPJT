"""주 이동 (T34): 과거·미래 주의 계획 등록·조회와 주별 기록 입력. 오늘은 2026-W46(11월 10일)이다."""
import pytest

from tests.test_web import FORM, SHOT_BODY, W46, env, make_plan, plan_with, signup, user  # noqa: F401

PAST, NEXT, FAR = "2026-W44", "2026-W47", "2026-W50"


def weeks(c):
    return c.get("/plans/weeks").json()


def test_weeks_list_is_empty_at_first_and_knows_the_current_week(user):
    assert weeks(user) == {"current": "2026-W46", "weeks": []}


def test_plans_for_past_current_and_future_weeks_are_kept_apart(user, env):
    for week, goal in ((PAST, "자유투"), ("2026-W46", "3점슛"), (NEXT, "레이업")):
        r = make_plan(user, {**FORM, "week": week, "goals": [goal]}).json()
        assert r["status"] == "confirmed" and r["plan"]["week"] == week, r
    assert weeks(user)["weeks"] == [PAST, "2026-W46", NEXT]  # 오래된 주부터
    assert user.get("/plans/current").json()["week"] == "2026-W46"  # week를 안 주면 이번 주
    for week, goal in ((PAST, "자유투"), ("2026-W46", "3점슛"), (NEXT, "레이업")):
        got = user.get("/plans/current", params={"week": week}).json()
        assert got["week"] == week and got["input"]["goals"] == [goal]  # 주마다 자기 계획만


def test_a_week_without_a_plan_is_null(user):
    assert user.get("/plans/current", params={"week": PAST}).json() is None


def test_a_draft_for_another_week_is_not_saved_until_confirmed_and_saves_to_that_week(user):
    draft = user.post("/plans", json={**FORM, "week": NEXT}).json()
    assert draft["status"] == "pending" and draft["plan"]["week"] == NEXT
    assert weeks(user)["weeks"] == []
    done = user.post(f"/plans/{draft['plan_id']}/decision", json={"decision": "confirm"}).json()
    assert done["plan"]["week"] == NEXT and weeks(user)["weeks"] == [NEXT]
    assert user.get("/plans/current").json() is None  # 이번 주 계획은 아직 없다


def test_the_difficulty_of_a_week_comes_from_the_week_before_it(user, env):
    make_plan(user, {**FORM, "week": PAST})  # W44 계획: 볼 핸들링, 한 손 드리블
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["쉬웠음"], "week": PAST})
    env.gen.plan_fn = lambda u, v, j: plan_with("제자리 한 손 드리블", "양손 크로스오버 드리블")
    after = make_plan(user, {**FORM, "week": "2026-W45", "equipment": [], "days_per_week": 1, "level": "초급"}).json()["plan"]
    assert {j["drill"]: j["verdict"] for j in after["last_week"]}["제자리 볼 핸들링"] == "상향"  # W44 기록이 W45 계획에 반영
    before = make_plan(user, {**FORM, "week": "2026-W43"}).json()["plan"]
    assert before["last_week"] == []  # W42 계획이 없으니 반영할 지난주 결과가 없다


def test_records_can_be_entered_for_past_and_current_weeks_but_not_future_weeks(user):
    make_plan(user, {**FORM, "week": PAST})
    make_plan(user, FORM)
    make_plan(user, {**FORM, "week": NEXT})
    assert user.post("/records", json={**SHOT_BODY, "week": PAST}).status_code == 200
    assert user.post("/records", json=SHOT_BODY).status_code == 200  # 이번 주
    assert user.post("/records", json={**SHOT_BODY, "week": "2026-W46"}).status_code == 200
    r = user.post("/records", json={**SHOT_BODY, "week": NEXT})
    assert r.status_code == 422 and "아직 오지 않은 주" in r.json()["detail"]


def test_records_are_kept_per_week(user):
    make_plan(user, {**FORM, "week": PAST})
    make_plan(user, FORM)
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["어려웠음"], "week": PAST, "slot": "월"})
    past = {r["drill"]: r for r in user.get("/records/week", params={"week": PAST}).json() if r["slot"] == "월"}
    now = {r["drill"]: r for r in user.get("/records/week").json() if r["slot"] == "월"}
    assert past["제자리 볼 핸들링"]["ratings"] == ["어려웠음"] and past["제자리 볼 핸들링"]["verdict"] == "하향"
    assert now["제자리 볼 핸들링"]["ratings"] == [] and now["제자리 볼 핸들링"]["carry_over"] is True  # 이번 주에는 섞이지 않는다


@pytest.mark.parametrize("bad", ["2026-46", "2026-W5", "2026-W60", "2026-W00", "abc", "", "2026-W46 ", "2020-W46", "2030-W46", "26-W46"])
def test_invalid_or_out_of_range_weeks_are_rejected_everywhere(user, bad):
    assert user.post("/plans", json={**FORM, "week": bad}).status_code == 422
    assert user.get("/plans/current", params={"week": bad}).status_code == 422
    assert user.get("/records/week", params={"week": bad}).status_code == 422
    assert user.post("/records", json={**SHOT_BODY, "week": bad}).status_code == 422


def test_the_edges_of_the_52_week_range(user):
    assert user.get("/plans/current", params={"week": "2025-W46"}).status_code == 200  # 52주 전
    assert user.get("/plans/current", params={"week": "2027-W45"}).status_code == 200  # 52주 뒤
    assert user.get("/plans/current", params={"week": "2025-W45"}).status_code == 422
    assert user.get("/plans/current", params={"week": "2027-W46"}).status_code == 422


def test_weeks_endpoint_requires_login_and_is_per_user(env, user):
    from fastapi.testclient import TestClient

    make_plan(user, {**FORM, "week": PAST})
    assert TestClient(env.app).get("/plans/weeks").status_code == 401
    other = TestClient(env.app)
    signup(other, "jisu")
    assert weeks(other)["weeks"] == [] and weeks(user)["weeks"] == [PAST]


def test_the_week_in_the_current_plan_matches_after_the_clock_moves(user, env):
    from tests.test_web import W47

    make_plan(user, FORM)  # W46
    env.clock.today = W47
    assert user.get("/plans/current").json() is None  # 이번 주가 W47로 바뀌면 W46 계획은 '이번 주'가 아니다
    assert user.get("/plans/current", params={"week": "2026-W46"}).json()["week"] == "2026-W46"
    assert weeks(user) == {"current": "2026-W47", "weeks": ["2026-W46"]}
