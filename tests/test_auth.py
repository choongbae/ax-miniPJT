from datetime import datetime, timedelta, timezone

import pytest

from src.auth import (
    GUEST_ID,
    AuthError,
    AuthService,
    LoginLimiter,
    hash_password,
    hash_token,
    new_token,
    validate_credentials,
    verify_password,
)
from src.store import SqliteStore

START = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.t = START

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class Mono:
    """LoginLimiter용 가짜 시계."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    store = SqliteStore(tmp_path / "app.db")
    clock, mono = Clock(), Mono()
    return SimpleEnv(store, AuthService(store, LoginLimiter(clock=mono), now=clock), clock, mono, tmp_path / "app.db")


class SimpleEnv:
    def __init__(self, store, auth, clock, mono, path):
        self.store, self.auth, self.clock, self.mono, self.path = store, auth, clock, mono, path


# --- 입력 형식 -------------------------------------------------------------------------

@pytest.mark.parametrize(
    "username,password,fragment",
    [
        ("ab", "password123", "3~32자"),
        ("a" * 33, "password123", "3~32자"),
        ("min su", "password123", "3~32자"),
        ("min'su", "password123", "3~32자"),
        ("../etc", "password123", "3~32자"),
        ("admin", "password123", "사용할 수 없는"),
        ("Default", "password123", "사용할 수 없는"),
        ("minsu", "short", "8~128자"),
        ("minsu", "x" * 129, "8~128자"),
        ("minsu123", "MINSU123", "아이디와 달라야"),
    ],
)
def test_bad_credentials_are_rejected_with_a_korean_message(username, password, fragment):
    errors = validate_credentials(username, password)
    assert errors and fragment in " ".join(errors)


@pytest.mark.parametrize("username", ["minsu", "민수01", "min_su-2", "abc"])
def test_good_usernames_pass(username):
    assert validate_credentials(username, "correct-horse-1") == []


# --- 비밀번호와 토큰 -------------------------------------------------------------------

def test_password_hash_verifies_and_rejects_wrong_password():
    h, s = hash_password("비밀번호-1234")
    assert verify_password("비밀번호-1234", h, s) and not verify_password("비밀번호-1235", h, s)
    assert "비밀번호" not in h


def test_same_password_gets_different_salt_and_hash():
    (h1, s1), (h2, s2) = hash_password("same-password"), hash_password("same-password")
    assert s1 != s2 and h1 != h2


def test_tokens_are_random_and_hashed():
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 40
    assert hash_token(a) != a and hash_token(a) == hash_token(a) and len(hash_token(a)) == 64


# --- 가입과 로그인 ---------------------------------------------------------------------

def test_register_then_login_returns_a_token_that_identifies_the_user(env):
    assert env.auth.register("minsu", "correct-horse-1") == "minsu"
    username, token = env.auth.login("minsu", "correct-horse-1")
    assert username == "minsu" and env.auth.user_for_token(token) == "minsu"


def test_login_ignores_username_case_and_returns_the_registered_spelling(env):
    env.auth.register("MinSu", "correct-horse-1")
    username, _ = env.auth.login("minsu", "correct-horse-1")
    assert username == "MinSu"


def test_duplicate_username_is_rejected_ignoring_case(env):
    env.auth.register("minsu", "correct-horse-1")
    with pytest.raises(AuthError) as e:
        env.auth.register("MINSU", "another-pass-2")
    assert e.value.status == 409 and "이미 사용 중" in e.value.message


def test_register_with_bad_input_is_422(env):
    with pytest.raises(AuthError) as e:
        env.auth.register("a", "x")
    assert e.value.status == 422


def test_guest_id_cannot_be_registered(env):
    with pytest.raises(AuthError) as e:
        env.auth.register(GUEST_ID, "correct-horse-1")
    assert e.value.status == 422


def test_wrong_password_and_unknown_user_give_the_same_error(env):
    env.auth.register("minsu", "correct-horse-1")
    with pytest.raises(AuthError) as wrong:
        env.auth.login("minsu", "wrong-password-9")
    with pytest.raises(AuthError) as unknown:
        env.auth.login("nobody", "wrong-password-9")
    assert wrong.value.status == unknown.value.status == 401
    assert wrong.value.message == unknown.value.message  # 아이디가 있는지 알아낼 수 없다


# --- 저장된 값 -------------------------------------------------------------------------

def test_database_never_contains_the_password_or_the_raw_token(env):
    env.auth.register("minsu", "very-secret-pass-77")
    _, token = env.auth.login("minsu", "very-secret-pass-77")
    raw = b"".join(p.read_bytes() for p in env.path.parent.glob("app.db*"))
    assert b"very-secret-pass-77" not in raw
    assert token.encode() not in raw
    assert hash_token(token).encode() in raw  # 토큰은 해시로만 저장된다


# --- 세션 ------------------------------------------------------------------------------

def test_session_expires_after_seven_days(env):
    env.auth.register("minsu", "correct-horse-1")
    _, token = env.auth.login("minsu", "correct-horse-1")
    env.clock.advance(days=6, hours=23)
    assert env.auth.user_for_token(token) == "minsu"
    env.clock.advance(hours=2)
    assert env.auth.user_for_token(token) is None


def test_logout_invalidates_only_that_session(env):
    env.auth.register("minsu", "correct-horse-1")
    _, first = env.auth.login("minsu", "correct-horse-1")
    _, second = env.auth.login("minsu", "correct-horse-1")
    env.auth.logout(first)
    assert env.auth.user_for_token(first) is None and env.auth.user_for_token(second) == "minsu"


@pytest.mark.parametrize("token", [None, "", "not-a-real-token", "x" * 43])
def test_unknown_or_missing_tokens_identify_nobody(env, token):
    assert env.auth.user_for_token(token) is None


def test_logout_with_missing_token_does_nothing(env):
    env.auth.logout(None)
    env.auth.logout("unknown")


def test_two_users_have_separate_sessions(env):
    env.auth.register("minsu", "correct-horse-1")
    env.auth.register("jiyeon", "battery-staple-2")
    _, t1 = env.auth.login("minsu", "correct-horse-1")
    _, t2 = env.auth.login("jiyeon", "battery-staple-2")
    assert env.auth.user_for_token(t1) == "minsu" and env.auth.user_for_token(t2) == "jiyeon"


# --- 로그인 시도 제한 --------------------------------------------------------------------

def test_repeated_failures_lock_the_account_for_a_while(env):
    env.auth.register("minsu", "correct-horse-1")
    for _ in range(5):
        with pytest.raises(AuthError) as e:
            env.auth.login("minsu", "wrong-password-9")
        assert e.value.status == 401
    with pytest.raises(AuthError) as locked:
        env.auth.login("minsu", "correct-horse-1")  # 맞는 비밀번호도 막힌다
    assert locked.value.status == 429 and "초 뒤에" in locked.value.message
    env.mono.t += 61
    assert env.auth.login("minsu", "correct-horse-1")[0] == "minsu"  # 시간이 지나면 풀린다


def test_a_successful_login_resets_the_failure_count(env):
    env.auth.register("minsu", "correct-horse-1")
    for _ in range(4):
        with pytest.raises(AuthError):
            env.auth.login("minsu", "wrong-password-9")
    env.auth.login("minsu", "correct-horse-1")
    for _ in range(4):  # 다시 4번 틀려도 막히지 않는다
        with pytest.raises(AuthError) as e:
            env.auth.login("minsu", "wrong-password-9")
        assert e.value.status == 401


def test_lock_is_per_username(env):
    env.auth.register("minsu", "correct-horse-1")
    env.auth.register("jiyeon", "battery-staple-2")
    for _ in range(5):
        with pytest.raises(AuthError):
            env.auth.login("minsu", "wrong-password-9")
    assert env.auth.login("jiyeon", "battery-staple-2")[0] == "jiyeon"


def test_failures_outside_the_window_do_not_add_up():
    mono = Mono()
    limiter = LoginLimiter(max_failures=3, window=100, lock=60, clock=mono)
    limiter.failure("u")
    limiter.failure("u")
    mono.t += 101
    limiter.failure("u")
    assert limiter.retry_after("u") == 0
