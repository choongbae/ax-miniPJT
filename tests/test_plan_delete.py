"""주별 계획 삭제 (T40): DELETE /plans?week= 는 그 주의 계획과 수행 기록을 함께 지운다."""
import pytest
from fastapi.testclient import TestClient

from tests.test_web import FORM, SHOT_BODY, env, make_plan, plan_with, signup, user  # noqa: F401

PAST, CUR, NEXT = "2026-W44", "2026-W46", "2026-W47"


def delete(c, week):
    return c.delete("/plans", params={"week": week})


def record_some(c, week):
    assert c.post("/records", json={**SHOT_BODY, "week": week}).status_code == 200
    assert c.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["쉬웠음", "적당"], "week": week}).status_code == 200
    return 3


def test_deleting_removes_the_plan_and_that_weeks_records_and_reports_the_count(user, env):
    make_plan(user, FORM)
    n = record_some(user, CUR)
    r = delete(user, CUR)
    assert r.status_code == 200 and r.json() == {"week": CUR, "deleted_records": n}
    assert user.get("/plans/current").json() is None
    assert CUR not in user.get("/plans/weeks").json()["weeks"]
    assert env.store.count_week_records("minsu", CUR) == 0
    assert env.store.get_plan("minsu", CUR) is None


def test_a_plan_without_records_deletes_with_zero(user):
    make_plan(user, FORM)
    assert delete(user, CUR).json()["deleted_records"] == 0


def test_other_weeks_and_other_users_are_untouched(user, env):
    for week in (PAST, CUR, NEXT):
        make_plan(user, {**FORM, "week": week})
    record_some(user, PAST)
    record_some(user, CUR)
    other = TestClient(env.app)
    signup(other, "jisu")
    make_plan(other, FORM)
    record_some(other, CUR)
    delete(user, CUR)
    assert user.get("/plans/weeks").json()["weeks"] == [PAST, NEXT]
    assert env.store.count_week_records("minsu", PAST) == 3  # 다른 주 기록은 그대로
    assert env.store.get_plan("jisu", CUR) is not None and env.store.count_week_records("jisu", CUR) == 3  # 다른 사용자도 그대로


def test_a_future_week_plan_can_be_deleted(user):
    make_plan(user, {**FORM, "week": NEXT})
    assert delete(user, NEXT).status_code == 200
    assert user.get("/plans/current", params={"week": NEXT}).json() is None


def test_a_week_without_a_plan_is_404_and_a_second_delete_too(user):
    assert delete(user, CUR).status_code == 404
    make_plan(user, FORM)
    assert delete(user, CUR).status_code == 200
    r = delete(user, CUR)
    assert r.status_code == 404 and "삭제할 계획이 없어요" in r.json()["detail"]


def test_the_week_is_required_and_validated(user):
    make_plan(user, FORM)
    assert user.delete("/plans").status_code == 422  # 주를 빠뜨려 이번 주가 지워지는 일은 없다
    for bad in ("2026-46", "abc", "2026-W60", "2030-W10"):
        assert delete(user, bad).status_code == 422
    assert user.get("/plans/current").json() is not None  # 아무것도 지워지지 않았다


def test_login_is_required(env, user):
    make_plan(user, FORM)
    assert delete(TestClient(env.app), CUR).status_code == 401
    assert user.get("/plans/current").json() is not None


def test_a_pending_draft_of_that_week_is_dropped_but_other_weeks_drafts_are_not(user, env):
    make_plan(user, FORM)
    draft = user.post("/plans", json={**FORM, "week": CUR}).json()
    assert draft["status"] == "pending"
    delete(user, CUR)
    assert user.post(f"/plans/{draft['plan_id']}/decision", json={"decision": "confirm"}).status_code == 404  # 삭제 뒤 확정 못 한다
    make_plan(user, FORM)
    other = user.post("/plans", json={**FORM, "week": NEXT}).json()  # 사용자당 초안은 1개: 이번 초안은 다른 주 것
    delete(user, CUR)
    assert user.post(f"/plans/{other['plan_id']}/decision", json={"decision": "confirm"}).status_code == 200


def test_the_deleted_weeks_records_no_longer_count_for_the_next_weeks_plan(user, env):
    make_plan(user, {**FORM, "week": PAST})
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["쉬웠음", "쉬웠음"], "week": PAST})
    env.gen.plan_fn = lambda u, v, j: plan_with("제자리 한 손 드리블", "양손 크로스오버 드리블")
    first = make_plan(user, {**FORM, "week": "2026-W45", "equipment": [], "days_per_week": 1, "level": "초급"}).json()["plan"]["last_week"]
    assert {j["drill"]: j["verdict"] for j in first}["제자리 볼 핸들링"] == "상향"
    delete(user, PAST)  # W44 계획과 기록 삭제
    env.gen.plan_fn = None
    second = make_plan(user, {**FORM, "week": "2026-W45"}).json()["plan"]["last_week"]
    assert second == []  # 반영할 지난주 계획이 없다


def test_the_progress_screen_forgets_a_deleted_week(user):
    make_plan(user, FORM)
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["쉬웠음"]})
    assert any(f["has_data"] for f in user.get("/progress").json()["fields"])
    delete(user, CUR)
    assert not any(f["has_data"] for f in user.get("/progress").json()["fields"])


def test_deleting_every_plan_leaves_the_user_with_no_plan_weeks(user):
    for week in (PAST, CUR):
        make_plan(user, {**FORM, "week": week})
    delete(user, PAST)
    delete(user, CUR)
    assert user.get("/plans/weeks").json()["weeks"] == []  # 화면은 이 때 "처음 시작했어요" 선택을 다시 보인다 (T38)


def test_a_week_can_be_planned_again_after_deleting_it(user):
    make_plan(user, FORM)
    delete(user, CUR)
    again = make_plan(user, FORM).json()
    assert again["status"] == "confirmed" and again["resets_records"] == 0  # 계획이 없던 주로 돌아가 기록 초기화 경고도 없다
