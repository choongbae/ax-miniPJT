"""계정, 비밀번호, 세션 (T25). 표준 라이브러리만 쓴다.

- 비밀번호는 무작위 솔트와 함께 scrypt로 해시해 저장하고, 원문은 저장하지 않는다.
- 로그인하면 무작위 토큰을 발급한다. 저장소에는 토큰의 SHA-256 해시만 둔다(저장소가 새어도 토큰을 쓸 수 없다).
- 같은 아이디로 연속 실패하면 잠시 막는다.
- 존재하지 않는 아이디와 틀린 비밀번호는 같은 오류와 비슷한 시간으로 응답한다(아이디 존재 여부를 알아내지 못하게).
"""
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

USERNAME_PATTERN = re.compile(r"^[0-9A-Za-z_\-가-힣]{3,32}$")
RESERVED_USERNAMES = {"default", "guest", "admin", "root", "system"}  # default는 로그인 없이 쓰는 손님 계정이다
PASSWORD_MIN, PASSWORD_MAX = 8, 128
SESSION_DAYS = 7
SCRYPT_PARAMS = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
GUEST_ID = "default"


class AuthError(Exception):
    """사용자에게 보여 줄 수 있는 인증 오류. status는 HTTP 상태 코드로 쓴다."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def validate_credentials(username: str, password: str) -> list[str]:
    """아이디와 비밀번호 형식을 확인한다. 올바르면 빈 목록, 아니면 한국어 안내 목록."""
    errors: list[str] = []
    if not USERNAME_PATTERN.match(username):
        errors.append("아이디는 한글·영문·숫자·_·-로 3~32자여야 합니다.")
    elif username.lower() in RESERVED_USERNAMES:
        errors.append("사용할 수 없는 아이디입니다.")
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        errors.append(f"비밀번호는 {PASSWORD_MIN}~{PASSWORD_MAX}자여야 합니다.")
    elif password.lower() == username.lower():
        errors.append("비밀번호는 아이디와 달라야 합니다.")
    return errors


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """(해시, 솔트)를 16진수 문자열로 돌려준다."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, **SCRYPT_PARAMS)
    return digest.hex(), salt.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    candidate, _ = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(candidate, hash_hex)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class LoginLimiter:
    """같은 아이디로 window초 안에 max_failures번 실패하면 lock초 동안 막는다."""

    def __init__(self, max_failures: int = 5, window: float = 300, lock: float = 60, clock=time.monotonic):
        self.max_failures, self.window, self.lock, self.clock = max_failures, window, lock, clock
        self._failures: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}

    def retry_after(self, key: str) -> int:
        """막혀 있으면 남은 초, 아니면 0."""
        left = self._locked_until.get(key.lower(), 0) - self.clock()
        return max(0, int(left) + 1) if left > 0 else 0

    def failure(self, key: str) -> None:
        key, now = key.lower(), self.clock()
        recent = [t for t in self._failures.get(key, []) if now - t < self.window] + [now]
        self._failures[key] = recent
        if len(recent) >= self.max_failures:
            self._locked_until[key] = now + self.lock
            self._failures[key] = []

    def success(self, key: str) -> None:
        self._failures.pop(key.lower(), None)
        self._locked_until.pop(key.lower(), None)


_DUMMY_HASH, _DUMMY_SALT = hash_password("dummy-password-for-timing")


class AuthService:
    """store(SqliteStore)의 계정·세션 기능 위에서 가입, 로그인, 로그아웃, 토큰 확인을 한다."""

    def __init__(self, store, limiter: LoginLimiter | None = None, now=lambda: datetime.now(timezone.utc)):
        self.store = store
        self.limiter = limiter or LoginLimiter()
        self.now = now

    def _iso(self, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def register(self, username: str, password: str) -> str:
        errors = validate_credentials(username, password)
        if errors:
            raise AuthError(422, " ".join(errors))
        hash_hex, salt_hex = hash_password(password)
        if not self.store.create_user(username, hash_hex, salt_hex, self._iso(self.now())):
            raise AuthError(409, "이미 사용 중인 아이디입니다.")
        return username

    def login(self, username: str, password: str) -> tuple[str, str]:
        """(아이디, 세션 토큰)을 돌려준다. 실패하면 AuthError."""
        wait = self.limiter.retry_after(username)
        if wait:
            raise AuthError(429, f"로그인에 여러 번 실패해서 잠시 막았어요. {wait}초 뒤에 다시 시도해 주세요.")
        user = self.store.get_user(username)
        if user is None:
            verify_password(password, _DUMMY_HASH, _DUMMY_SALT)  # 아이디가 없어도 비슷한 시간이 걸리게 한다
            ok = False
        else:
            ok = verify_password(password, user["password_hash"], user["salt"])
        if not ok:
            self.limiter.failure(username)
            raise AuthError(401, "아이디 또는 비밀번호가 올바르지 않습니다.")
        self.limiter.success(username)
        token = new_token()
        expires = self.now() + timedelta(days=SESSION_DAYS)
        self.store.create_session(hash_token(token), user["username"], self._iso(expires))
        return user["username"], token

    def user_for_token(self, token: str | None) -> str | None:
        if not token:
            return None
        return self.store.find_session(hash_token(token), self._iso(self.now()))

    def logout(self, token: str | None) -> None:
        if token:
            self.store.delete_session(hash_token(token))
