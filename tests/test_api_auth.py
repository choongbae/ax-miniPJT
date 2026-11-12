"""로그인이 API에서 동작하는지 확인한다 (T25). 계정은 SQLite 저장소에 둔다."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.api import LOGIN_REQUIRED_DETAIL, SESSION_COOKIE, create_app
from src.orchestrator import ParsedRequest, QueryResponse, Report, SessionEntry, answer_question
from src.records import RecordStore
from src.store import SqliteStore
from src.tools import load_drills

CATALOG = load_drills()
PASSWORD = "correct-horse-1"


def echo_user(question, retriever=None, store=None, user_id="default"):
    echo_user.calls.append(user_id)
    return QueryResponse(answer=f"user={user_id}", contexts=[], trace=[], intent="knowledge")


@pytest.fixture(autouse=True)
def reset():
    echo_user.calls = []


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "app.db"


@pytest.fixture
def client(db_path):
    app = create_app(retriever=None, store=SqliteStore(db_path), answer_fn=echo_user)
    with TestClient(app) as c:
        yield c


def register(client, username="minsu", password=PASSWORD):
    return client.post("/auth/register", json={"username": username, "password": password})


def login(client, username="minsu", password=PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


# --- 가입 ----------------------------------------------------------------------------

def test_register_creates_an_account_without_returning_secrets(client):
    r = register(client)
    assert r.status_code == 201 and r.json() == {"username": "minsu"}
    assert PASSWORD not in r.text


def test_register_with_bad_input_gets_a_korean_message(client):
    r = register(client, "a", "x")
    assert r.status_code == 422 and "3~32자" in r.json()["detail"] and "8~128자" in r.json()["detail"]


def test_register_duplicate_is_409(client):
    register(client)
    r = register(client, "MINSU", "another-pass-2")
    assert r.status_code == 409 and "이미 사용 중" in r.json()["detail"]


def test_guest_name_cannot_be_registered(client):
    assert register(client, "default").status_code == 422


@pytest.mark.parametrize("payload", [{}, {"username": "minsu"}, {"password": PASSWORD}, {"username": "x" * 65, "password": PASSWORD}])
def test_malformed_register_bodies_are_422(client, payload):
    assert client.post("/auth/register", json=payload).status_code == 422


# --- 로그인 · 쿠키 -----------------------------------------------------------------------

def test_login_returns_token_and_sets_a_secure_style_cookie(client):
    register(client)
    r = login(client)
    assert r.status_code == 200 and r.json()["username"] == "minsu" and len(r.json()["token"]) >= 40
    cookie = r.headers["set-cookie"]
    assert f"{SESSION_COOKIE}={r.json()['token']}" in cookie
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Max-Age=604800" in cookie  # 7일
    assert "Secure" not in cookie  # 로컬 http에서는 쓰지 않는다


def test_cookie_gets_the_secure_flag_when_enabled(db_path):
    app = create_app(retriever=None, store=SqliteStore(db_path), answer_fn=echo_user, cookie_secure=True)
    with TestClient(app) as c:
        register(c)
        assert "Secure" in login(c).headers["set-cookie"]


def test_wrong_password_and_unknown_user_look_the_same(client):
    register(client)
    wrong, unknown = login(client, password="wrong-password-9"), login(client, "nobody", "wrong-password-9")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert "set-cookie" not in wrong.headers


def test_repeated_failures_are_rate_limited_with_429(client):
    register(client)
    codes = [login(client, password="wrong-password-9").status_code for _ in range(5)]
    assert codes == [401] * 5
    locked = login(client)  # 맞는 비밀번호도 잠시 막힌다
    assert locked.status_code == 429 and "초 뒤에" in locked.json()["detail"]


# --- 질문에서 로그인한 사용자로 구분 ---------------------------------------------------------

def test_query_without_login_uses_the_guest_user(client):
    client.post("/query", json={"question": "q"})
    assert echo_user.calls == ["default"]


def test_query_with_login_cookie_uses_that_user(client):
    register(client)
    login(client)
    body = client.post("/query", json={"question": "q"}).json()
    assert echo_user.calls == ["minsu"] and body["answer"] == "user=minsu"


def test_query_with_bearer_token_uses_that_user(client):
    register(client)
    token = login(client).json()["token"]
    client.cookies.clear()
    client.post("/query", json={"question": "q"}, headers={"Authorization": f"Bearer {token}"})
    assert echo_user.calls == ["minsu"]


@pytest.mark.parametrize("headers", [{"Authorization": "Bearer not-a-real-token"}, {"Authorization": "Bearer "}])
def test_invalid_token_is_rejected_not_treated_as_guest(client, headers):
    r = client.post("/query", json={"question": "q"}, headers=headers)
    if headers["Authorization"] == "Bearer ":
        assert r.status_code == 200  # 비어 있는 토큰은 토큰이 없는 것과 같다
    else:
        assert r.status_code == 401 and r.json() == {"detail": LOGIN_REQUIRED_DETAIL}
        assert echo_user.calls == []  # 답변 로직까지 가지 않는다


def test_invalid_cookie_is_rejected_too(client):
    client.cookies.set(SESSION_COOKIE, "forged-cookie-value")
    assert client.post("/query", json={"question": "q"}).status_code == 401


def test_x_user_id_header_cannot_impersonate_a_logged_in_user(client):
    register(client)
    login(client)
    client.post("/query", json={"question": "q"}, headers={"X-User-Id": "someone-else"})
    assert echo_user.calls == ["minsu"]


# --- me · 로그아웃 -----------------------------------------------------------------------

def test_me_requires_login(client):
    assert client.get("/auth/me").status_code == 401
    register(client)
    login(client)
    assert client.get("/auth/me").json() == {"username": "minsu"}


def test_logout_ends_the_session_everywhere(client):
    register(client)
    token = login(client).json()["token"]
    r = client.post("/auth/logout")
    assert r.status_code == 204
    client.cookies.clear()
    stale = client.post("/query", json={"question": "q"}, headers={"Authorization": f"Bearer {token}"})
    assert stale.status_code == 401  # 로그아웃한 토큰은 더 쓸 수 없다


def test_logout_without_login_is_harmless(client):
    assert client.post("/auth/logout").status_code == 204


# --- 두 사용자의 기록이 섞이지 않는다 · 재접속 --------------------------------------------------

def record_parsed(attempts, makes):
    return ParsedRequest(
        intent="record", reports=[Report(drill="3점슛", shot_sessions=[SessionEntry(attempts=attempts, makes=makes)])]
    )


def agent_with(parsed):
    def run(question, **kw):
        return answer_question(question, parse_fn=lambda q: parsed, catalog=CATALOG, today=date(2026, 11, 12), **kw)

    return run


def test_two_users_records_do_not_mix_and_survive_a_server_restart(db_path):
    parsed = {"minsu": record_parsed(50, 10), "jiyeon": record_parsed(50, 30)}
    current = {"who": "minsu"}

    def run(question, **kw):
        return agent_with(parsed[current["who"]])(question, **kw)

    app = create_app(retriever=None, store=SqliteStore(db_path), answer_fn=run)
    with TestClient(app) as c1, TestClient(app) as c2:
        register(c1, "minsu", PASSWORD)
        register(c2, "jiyeon", "battery-staple-2")
        login(c1, "minsu", PASSWORD)
        login(c2, "jiyeon", "battery-staple-2")
        current["who"] = "minsu"
        a1 = c1.post("/query", json={"question": "기록"}).json()["answer"]
        current["who"] = "jiyeon"
        a2 = c2.post("/query", json={"question": "기록"}).json()["answer"]
        token = c1.cookies.get(SESSION_COOKIE)
    assert "난이도 하향" in a1 and "난이도 상향" in a2

    # 서버를 다시 띄워도(같은 DB 파일) 세션과 기록이 그대로 있다
    store = SqliteStore(db_path)
    assert store.shots("minsu", "3점 캐치앤슛", "2026-W46") == [(50, 10)]
    assert store.shots("jiyeon", "3점 캐치앤슛", "2026-W46") == [(50, 30)]
    assert not store.has_records("default")
    restarted = create_app(retriever=None, store=SqliteStore(db_path), answer_fn=echo_user)
    with TestClient(restarted) as c:
        r = c.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200 and r.json() == {"username": "minsu"}


def test_guest_records_stay_separate_from_accounts(db_path):
    run = agent_with(record_parsed(50, 10))
    app = create_app(retriever=None, store=SqliteStore(db_path), answer_fn=run)
    with TestClient(app) as c:
        register(c)
        c.post("/query", json={"question": "기록"})  # 로그인 없이
    store = SqliteStore(db_path)
    assert store.has_records("default") and not store.has_records("minsu")


# --- 계정을 지원하지 않는 저장소 ------------------------------------------------------------

def test_stores_without_accounts_answer_501(tmp_path):
    app = create_app(retriever=None, store=RecordStore(tmp_path / "r.json"), answer_fn=echo_user)
    with TestClient(app) as c:
        assert login(c).status_code == 501 and register(c).status_code == 501
        assert c.post("/query", json={"question": "q"}).status_code == 200  # 질문은 손님으로 계속 된다


# --- 새는 값이 없다 ---------------------------------------------------------------------

def test_no_response_contains_the_password_or_its_hash(client, db_path):
    texts = [register(client).text, login(client).text, client.get("/auth/me").text, client.post("/query", json={"question": "q"}).text]
    user = SqliteStore(db_path).get_user("minsu")
    for t in texts:
        assert PASSWORD not in t and user["password_hash"] not in t and user["salt"] not in t
