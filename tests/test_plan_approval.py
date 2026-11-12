"""계획 승인 흐름 테스트 (T26-1): 초안은 확정 전까지 저장되지 않고, 만든 사람만 확정·거절할 수 있다."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.api import create_app
from src.store import SqliteStore
from tests.test_web import FORM, PASSWORD, Clock, Gen, signup

START = datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc)


class Now:
    def __init__(self):
        self.t = START

    def __call__(self):
        return self.t


def build(tmp_path, gen=None, now=None):
    gen = gen or Gen()
    now = now or Now()
    app = create_app(retriever=None, store=SqliteStore(tmp_path / "app.db"), generate_fn=gen, today=Clock(), now=now)
    return app, gen, now


@pytest.fixture
def env(tmp_path):
    app, gen, now = build(tmp_path)
    with TestClient(app) as c:
        signup(c)
        yield type("Env", (), {"c": c, "app": app, "gen": gen, "now": now, "tmp": tmp_path, "store": app.state.store})


def draft(c, **change):
    r = c.post("/plans", json={**FORM, **change})
    assert r.status_code == 200 and r.json()["status"] == "pending", r.text
    return r.json()


def decide(c, plan_id, decision):
    return c.post(f"/plans/{plan_id}/decision", json={"decision": decision})


def test_a_new_plan_is_a_draft_that_is_not_saved_yet(env):
    body = draft(env.c)
    assert body["plan_id"] and body["plan"]["days"] and body["plan"]["week"] == "2026-W46"
    assert env.c.get("/plans/current").json() is None  # 확정 전에는 이번 주 계획이 아니다
    assert env.store.get_plan("minsu", "2026-W46") is None


def test_confirm_saves_the_plan_without_generating_again(env):
    body = draft(env.c)
    calls = len(env.gen.calls)
    r = decide(env.c, body["plan_id"], "confirm")
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert r.json()["plan"] == env.c.get("/plans/current").json()  # 저장된 것이 보여 준 초안 그대로
    assert r.json()["plan"]["days"] == body["plan"]["days"]
    assert len(env.gen.calls) == calls  # 확정할 때 모델을 다시 부르지 않는다
    assert r.json()["plan"]["input"]["goals"] == ["3점슛"]


def test_reject_saves_nothing_and_the_draft_is_gone(env):
    body = draft(env.c)
    r = decide(env.c, body["plan_id"], "reject")
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["plan"] is None
    assert env.c.get("/plans/current").json() is None
    assert decide(env.c, body["plan_id"], "confirm").status_code == 404  # 이미 정리됐다


def test_a_draft_cannot_be_decided_twice(env):
    body = draft(env.c)
    assert decide(env.c, body["plan_id"], "confirm").status_code == 200
    assert decide(env.c, body["plan_id"], "confirm").status_code == 404


def test_rejecting_keeps_the_previously_confirmed_plan(env):
    first = decide(env.c, draft(env.c)["plan_id"], "confirm").json()["plan"]
    again = draft(env.c, goals=["왼손 드리블"])
    decide(env.c, again["plan_id"], "reject")
    assert env.c.get("/plans/current").json() == first


def test_only_the_owner_can_decide_and_others_cannot_tell_it_exists(env):
    body = draft(env.c)
    other = TestClient(env.app)
    signup(other, "jisu")
    r = decide(other, body["plan_id"], "confirm")
    assert r.status_code == 404 and r.json()["detail"] == decide(other, "없는ID", "confirm").json()["detail"]
    assert other.get("/plans/current").json() is None and env.c.get("/plans/current").json() is None
    assert decide(env.c, body["plan_id"], "confirm").status_code == 200  # 주인은 여전히 확정할 수 있다


def test_decision_requires_login_and_a_valid_value(env):
    body = draft(env.c)
    assert decide(TestClient(env.app), body["plan_id"], "confirm").status_code == 401
    assert decide(env.c, body["plan_id"], "maybe").status_code == 422
    assert decide(env.c, body["plan_id"], "confirm").status_code == 200  # 잘못된 요청이 초안을 없애지 않았다


def test_draft_expires_after_24_hours(env):
    body = draft(env.c)
    env.now.t = START + timedelta(hours=23, minutes=59)
    ok = draft(env.c)  # 23시간 59분은 아직 유효 (새 초안이 이전 초안을 대체한다)
    env.now.t = START + timedelta(hours=23, minutes=59) + timedelta(hours=24, minutes=1)
    r = decide(env.c, ok["plan_id"], "confirm")
    assert r.status_code == 410 and "만료" in r.json()["detail"]
    assert env.c.get("/plans/current").json() is None
    assert decide(env.c, ok["plan_id"], "confirm").status_code == 404  # 만료된 초안은 정리된다
    assert body["plan_id"] != ok["plan_id"]


def test_a_draft_just_inside_the_limit_can_still_be_confirmed(env):
    body = draft(env.c)
    env.now.t = START + timedelta(hours=23, minutes=59)
    assert decide(env.c, body["plan_id"], "confirm").status_code == 200


def test_a_new_draft_replaces_the_old_one(env):
    first, second = draft(env.c), draft(env.c, goals=["레이업"])
    assert first["plan_id"] != second["plan_id"]
    assert decide(env.c, first["plan_id"], "confirm").status_code == 404
    assert decide(env.c, second["plan_id"], "confirm").json()["plan"]["input"]["goals"] == ["레이업"]


def test_a_draft_survives_a_server_restart(tmp_path):
    app, _, now = build(tmp_path)
    with TestClient(app) as c:
        signup(c)
        body = draft(c)
    app2, gen2, _ = build(tmp_path, now=now)  # 같은 DB 파일로 새 앱 = 서버 재시작
    with TestClient(app2) as c2:
        assert c2.post("/auth/login", json={"username": "minsu", "password": PASSWORD}).status_code == 200
        r = decide(c2, body["plan_id"], "confirm")
        assert r.status_code == 200 and r.json()["plan"]["days"] == body["plan"]["days"]
        assert gen2.calls == []  # 새 서버는 계획을 다시 만들지 않았다


def test_failed_plans_leave_no_draft(tmp_path):
    from tests.test_web import plan_with

    app, _, _ = build(tmp_path, gen=Gen(lambda u, v, j: plan_with("제자리 볼 핸들링", minutes=999)))
    with TestClient(app) as c:
        signup(c)
        r = c.post("/plans", json=FORM).json()
        assert r["status"] == "failed" and r["plan_id"] is None
        with app.state.store._conn() as conn:
            assert conn.execute("SELECT COUNT(*) FROM plan_drafts").fetchone()[0] == 0


def test_checkpoints_are_cleaned_up_after_a_decision(env):
    import sqlite3

    def threads():
        with sqlite3.connect(env.tmp / "checkpoints.db") as conn:
            return conn.execute("SELECT COUNT(DISTINCT thread_id) FROM checkpoints").fetchone()[0]

    a = draft(env.c)
    assert threads() == 1
    decide(env.c, a["plan_id"], "confirm")
    assert threads() == 0
    decide(env.c, draft(env.c)["plan_id"], "reject")
    assert threads() == 0


def test_the_draft_id_is_hard_to_guess(env):
    assert len(draft(env.c)["plan_id"]) >= 20
