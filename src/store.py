"""SQLite 저장소 (T25). 계정, 세션, 연습 기록, 주간 계획을 한 파일 DB에 둔다.

기록·계획 부분은 JSON 파일 저장소(src/records.py의 RecordStore)와 같은 메서드 이름과 동작이라 그대로 바꿔 쓸 수 있다.
요청마다 연결을 새로 열고 닫아서 동시 요청에도 안전하고, 모든 질의는 매개변수로 넘긴다(SQL 주입 방지).
"""
import json
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from src.models import WeeklyPlan
from src.records import previous_week_keys, validate_rating, validate_shot_record

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shot_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL, drill TEXT NOT NULL, week TEXT NOT NULL,
    attempts INTEGER NOT NULL, makes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rating_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL, drill TEXT NOT NULL, week TEXT NOT NULL, rating TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    user_id TEXT NOT NULL, week TEXT NOT NULL, plan_json TEXT NOT NULL, meta_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (user_id, week)
);
CREATE TABLE IF NOT EXISTS plan_drafts (
    plan_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, week TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shots ON shot_records (user_id, drill, week);
CREATE INDEX IF NOT EXISTS idx_ratings ON rating_records (user_id, drill, week);
"""


class SqliteStore:
    def __init__(self, path: Path | str = DEFAULT_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            columns = [row["name"] for row in conn.execute("PRAGMA table_info(plans)")]
            if "meta_json" not in columns:  # 메타가 없던 시절에 만든 DB를 고친다
                conn.execute("ALTER TABLE plans ADD COLUMN meta_json TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- 연습 기록과 계획 (RecordStore와 같은 인터페이스) -----------------------------------
    def add_shot(self, user_id: str, drill: str, week: str, attempts: int, makes: int) -> list[str]:
        errors = validate_shot_record(attempts, makes)
        if errors:
            return errors
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO shot_records (user_id, drill, week, attempts, makes) VALUES (?, ?, ?, ?, ?)",
                (user_id, drill, week, int(attempts), int(makes)),
            )
        return []

    def add_rating(self, user_id: str, drill: str, week: str, rating: str) -> list[str]:
        errors = validate_rating(rating)
        if errors:
            return errors
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO rating_records (user_id, drill, week, rating) VALUES (?, ?, ?, ?)",
                (user_id, drill, week, rating),
            )
        return []

    def shots(self, user_id: str, drill: str, week: str) -> list[tuple[int, int]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT attempts, makes FROM shot_records WHERE user_id = ? AND drill = ? AND week = ? ORDER BY id",
                (user_id, drill, week),
            ).fetchall()
        return [(r["attempts"], r["makes"]) for r in rows]

    def ratings(self, user_id: str, drill: str, week: str) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT rating FROM rating_records WHERE user_id = ? AND drill = ? AND week = ? ORDER BY id",
                (user_id, drill, week),
            ).fetchall()
        return [r["rating"] for r in rows]

    def past_weeks(self, user_id: str, drill: str, week: str, n: int = 4) -> list[tuple[int, int]]:
        result = []
        for key in previous_week_keys(week, n):
            sessions = self.shots(user_id, drill, key)
            if sessions:
                result.append((sum(a for a, _ in sessions), sum(m for _, m in sessions)))
        return result

    def save_plan(self, user_id: str, week: str, plan: WeeklyPlan, meta: dict | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO plans (user_id, week, plan_json, meta_json) VALUES (?, ?, ?, ?)",
                (user_id, week, json.dumps(plan.model_dump(), ensure_ascii=False), json.dumps(meta or {}, ensure_ascii=False)),
            )

    # -- 승인 대기 중인 계획 초안 (T26-1). 사용자당 1개, 만든 사람에게만 보인다 --------------------
    def create_draft(self, user_id: str, week: str, created_at: str) -> tuple[str, list[str]]:
        """새 초안 ID를 만들고, 같은 사용자의 이전 초안을 지운다. (새 ID, 지워진 이전 ID들)를 돌려준다."""
        plan_id = secrets.token_urlsafe(16)
        with self._conn() as conn:
            old = [r["plan_id"] for r in conn.execute("SELECT plan_id FROM plan_drafts WHERE user_id = ?", (user_id,))]
            conn.execute("DELETE FROM plan_drafts WHERE user_id = ?", (user_id,))
            conn.execute(
                "INSERT INTO plan_drafts (plan_id, user_id, week, created_at) VALUES (?, ?, ?, ?)",
                (plan_id, user_id, week, created_at),
            )
        return plan_id, old

    def get_draft(self, plan_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM plan_drafts WHERE plan_id = ?", (plan_id,)).fetchone()
        return dict(row) if row else None

    def delete_draft(self, plan_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM plan_drafts WHERE plan_id = ?", (plan_id,))

    def get_plan_meta(self, user_id: str, week: str) -> dict:
        with self._conn() as conn:
            row = conn.execute("SELECT meta_json FROM plans WHERE user_id = ? AND week = ?", (user_id, week)).fetchone()
        return json.loads(row["meta_json"]) if row else {}

    def records_for_weeks(self, user_id: str, weeks: list[str]) -> dict[str, dict[str, dict]]:
        out: dict[str, dict[str, dict]] = {}
        if not weeks:
            return out
        marks = ",".join("?" for _ in weeks)
        with self._conn() as conn:
            shots = conn.execute(
                f"SELECT week, drill, attempts, makes FROM shot_records WHERE user_id = ? AND week IN ({marks}) ORDER BY id", (user_id, *weeks)
            ).fetchall()
            ratings = conn.execute(
                f"SELECT week, drill, rating FROM rating_records WHERE user_id = ? AND week IN ({marks}) ORDER BY id", (user_id, *weeks)
            ).fetchall()
        for r in shots:
            out.setdefault(r["week"], {}).setdefault(r["drill"], {"shots": [], "ratings": []})["shots"].append((r["attempts"], r["makes"]))
        for r in ratings:
            out.setdefault(r["week"], {}).setdefault(r["drill"], {"shots": [], "ratings": []})["ratings"].append(r["rating"])
        return out

    def count_week_records(self, user_id: str, week: str) -> int:
        with self._conn() as conn:
            return sum(
                conn.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ? AND week = ?", (user_id, week)).fetchone()[0]
                for table in ("shot_records", "rating_records")
            )

    def delete_week_records(self, user_id: str, week: str) -> int:
        with self._conn() as conn:
            removed = 0
            for table in ("shot_records", "rating_records"):
                removed += conn.execute(f"DELETE FROM {table} WHERE user_id = ? AND week = ?", (user_id, week)).rowcount
        return removed

    def plan_weeks(self, user_id: str) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT week FROM plans WHERE user_id = ? ORDER BY week", (user_id,)).fetchall()
        return [r["week"] for r in rows]

    def get_plan(self, user_id: str, week: str) -> WeeklyPlan | None:
        with self._conn() as conn:
            row = conn.execute("SELECT plan_json FROM plans WHERE user_id = ? AND week = ?", (user_id, week)).fetchone()
        return WeeklyPlan.model_validate(json.loads(row["plan_json"])) if row else None

    def has_records(self, user_id: str) -> bool:
        with self._conn() as conn:
            for table in ("shot_records", "rating_records", "plans"):
                if conn.execute(f"SELECT 1 FROM {table} WHERE user_id = ? LIMIT 1", (user_id,)).fetchone():
                    return True
        return False

    def user_ids(self) -> list[str]:
        """계정이 있거나 기록·계획이 있는 모든 사용자. 출력 점검에서 다른 사용자 이름이 섞였는지 볼 때 쓴다."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT username AS u FROM users UNION SELECT user_id FROM shot_records "
                "UNION SELECT user_id FROM rating_records UNION SELECT user_id FROM plans"
            ).fetchall()
        return sorted(r["u"] for r in rows)

    # -- 계정과 세션 -----------------------------------------------------------------------
    def create_user(self, username: str, password_hash: str, salt: str, created_at: str) -> bool:
        """계정을 만든다. 같은 아이디(대소문자 무시)가 이미 있으면 False."""
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
                    (username, password_hash, salt, created_at),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def get_user(self, username: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT username, password_hash, salt FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None

    def create_session(self, token_hash: str, username: str, expires_at: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, username, expires_at) VALUES (?, ?, ?)", (token_hash, username, expires_at)
            )

    def find_session(self, token_hash: str, now_iso: str) -> str | None:
        """만료되지 않은 세션의 아이디. 없거나 만료되었으면 None(만료된 세션은 지운다)."""
        with self._conn() as conn:
            row = conn.execute("SELECT username, expires_at FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone()
            if row is None:
                return None
            if row["expires_at"] <= now_iso:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
                return None
            return row["username"]

    def delete_session(self, token_hash: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
