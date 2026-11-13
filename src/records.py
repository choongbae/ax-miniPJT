"""연습 기록의 입력 검증과 임시 저장 (JSON 파일).

사용자별 DB는 묶음 5(로그인·DB)에서 정한다. 그때까지 이 파일 저장소로 기록을 모은다.
기록은 한 번의 연습에서 한 연습 메뉴당 (슛이면 시도·성공 수, 슛 외면 자기평가) 하나씩 넣는다.
"""
import json
import threading
import re
from datetime import date, timedelta
from pathlib import Path

from src.models import RATINGS, Drill, WeeklyPlan
from src.tools import DrillJudgment, judge_drill

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "records.json"


def week_key(d: date) -> str:
    """날짜가 속한 ISO 주 (예: 2026-W46). 주는 월요일에 시작한다."""
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def plan_slots(plan: WeeklyPlan) -> list[tuple[str, str]]:
    """계획의 카드마다 (연습 메뉴 이름, 슬롯). 슬롯은 요일이고, 같은 요일에 같은 메뉴가 또 나오면 '월#2'처럼 번호를 붙인다."""
    out: list[tuple[str, str]] = []
    for day in plan.days:
        seen: dict[str, int] = {}
        for pd in day.drills:
            seen[pd.name] = seen.get(pd.name, 0) + 1
            out.append((pd.name, day.day if seen[pd.name] == 1 else f"{day.day}#{seen[pd.name]}"))
    return out


def week_start(week: str) -> date | None:
    """'2026-W46' 같은 주 값의 월요일. 형식이 틀리거나 없는 주(예: 2026-W60)면 None."""
    match = re.fullmatch(r"(\d{4})-W(\d{2})", week or "")
    if not match:
        return None
    try:
        return date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
    except ValueError:
        return None


def previous_week_keys(week: str, n: int = 4) -> list[str]:
    """주어진 주 바로 앞의 n개 주 (가까운 주부터)."""
    year, w = week.split("-W")
    monday = date.fromisocalendar(int(year), int(w), 1)
    return [week_key(monday - timedelta(weeks=i)) for i in range(1, n + 1)]


def next_week_key(week: str) -> str:
    """주어진 주의 다음 주."""
    year, w = week.split("-W")
    return week_key(date.fromisocalendar(int(year), int(w), 1) + timedelta(weeks=1))


def validate_shot_record(attempts: object, makes: object) -> list[str]:
    """슛 기록 검증. 올바르면 빈 목록, 아니면 한국어 안내 목록."""
    errors: list[str] = []
    try:
        a = int(attempts)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        errors.append("시도 수는 정수로 입력해 주세요.")
        a = None
    try:
        m = int(makes)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        errors.append("성공 수는 정수로 입력해 주세요.")
        m = None
    if a is not None and a < 1:
        errors.append("시도 수는 1 이상이어야 합니다.")
    if m is not None and m < 0:
        errors.append("성공 수는 0 이상이어야 합니다.")
    if a is not None and m is not None and a >= 1 and m > a:
        errors.append(f"성공 수({m})가 시도 수({a})보다 많을 수 없습니다.")
    return errors


def validate_rating(rating: object) -> list[str]:
    if rating in RATINGS:
        return []
    return ["자기평가는 쉬웠음, 적당, 어려웠음 중 하나여야 합니다."]


class RecordStore:
    """사용자별 연습 기록 저장소. 저장은 JSON 파일 하나에 한다."""

    def __init__(self, path: Path = DEFAULT_PATH):
        self.path = Path(path)
        self._entries: list[dict] = []
        self._lock = threading.RLock()  # API가 요청을 동시에 처리해도 파일이 깨지지 않게 쓰기를 한 번에 하나씩 한다
        if self.path.exists():
            self._entries = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._entries, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append(self, entry: dict) -> None:
        with self._lock:
            self._entries.append(entry)
            self._save()

    def add_shot(self, user_id: str, drill: str, week: str, attempts: int, makes: int) -> list[str]:
        """슛 기록을 저장한다. 값이 틀리면 저장하지 않고 안내 목록을 돌려준다."""
        errors = validate_shot_record(attempts, makes)
        if errors:
            return errors
        self._append({"user_id": user_id, "drill": drill, "week": week, "attempts": int(attempts), "makes": int(makes)})
        return []

    def add_rating(self, user_id: str, drill: str, week: str, rating: str) -> list[str]:
        errors = validate_rating(rating)
        if errors:
            return errors
        self._append({"user_id": user_id, "drill": drill, "week": week, "rating": rating})
        return []

    def save_plan(self, user_id: str, week: str, plan: WeeklyPlan, meta: dict | None = None) -> None:
        """그 주에 사용자에게 준 계획을 저장한다. 같은 주에 다시 만들면 새 계획으로 바꾼다.

        meta는 화면에 같은 내용을 다시 그리기 위한 값(입력, 안내, 이야기, 지난주 결과)이다."""
        with self._lock:
            self._entries = [e for e in self._entries if not (e["user_id"] == user_id and e["week"] == week and "plan" in e)]
            self._entries.append({"user_id": user_id, "week": week, "plan": plan.model_dump(), "meta": meta or {}})
            self._save()

    def get_plan_meta(self, user_id: str, week: str) -> dict:
        for e in reversed(self._entries):
            if e["user_id"] == user_id and e["week"] == week and "plan" in e:
                return e.get("meta", {})
        return {}

    def records_for_weeks(self, user_id: str, weeks: list[str]) -> dict[str, dict[str, dict]]:
        """여러 주의 기록을 한 번에: {주: {연습 메뉴: {"shots": [(시도, 성공)], "ratings": [평가]}}}. 기록이 있는 것만 담는다."""
        wanted = set(weeks)
        out: dict[str, dict[str, dict]] = {}
        for e in self._entries:
            if e["user_id"] != user_id or e["week"] not in wanted or "plan" in e:
                continue
            slot = out.setdefault(e["week"], {}).setdefault(e["drill"], {"shots": [], "ratings": []})
            if "rating" in e:
                slot["ratings"].append(e["rating"])
            else:
                slot["shots"].append((e["attempts"], e["makes"]))
        return out

    def replace_record(
        self,
        user_id: str,
        drill: str,
        week: str,
        shot: tuple[int, int] | None = None,
        rating: str | None = None,
        slot: str = "",
        absorb_legacy: bool = False,
    ) -> list[str]:
        """그 연습 카드의 기록을 한 건으로 바꾼다 (웹 화면의 '등록 후 갱신'). 슛이면 shot=(시도, 성공), 아니면 rating.

        slot은 계획의 카드(요일, 같은 요일에 같은 메뉴가 또 나오면 '월#2')다. 그 카드의 기록만 바꾸고 같은 메뉴의 다른 카드는 건드리지 않는다.
        absorb_legacy=True이면 슬롯이 없던 예전 기록도 함께 지운다(그 메뉴의 첫 카드를 저장할 때). slot이 비어 있으면 그 메뉴·주의 기록 전체를 바꾼다.
        값이 틀리면 아무것도 바꾸지 않고 안내 목록을 돌려준다."""
        errors = validate_shot_record(*shot) if shot is not None else validate_rating(rating)
        if errors:
            return errors

        def replaced(e: dict) -> bool:
            if not (e["user_id"] == user_id and e["week"] == week and e.get("drill") == drill and "plan" not in e):
                return False
            own = e.get("slot", "")
            return slot == "" or own == slot or (absorb_legacy and own == "")

        with self._lock:
            self._entries = [e for e in self._entries if not replaced(e)]
            entry = {"user_id": user_id, "drill": drill, "week": week, "slot": slot}
            entry.update({"attempts": int(shot[0]), "makes": int(shot[1])} if shot is not None else {"rating": rating})
            self._entries.append(entry)
            self._save()
        return []

    def slot_records(self, user_id: str, week: str) -> dict[str, dict[str, dict]]:
        """그 주의 기록을 카드별로: {연습 메뉴: {슬롯: {"shots": [(시도, 성공)], "ratings": [평가]}}}. 슬롯이 없던 예전 기록은 슬롯 ''."""
        out: dict[str, dict[str, dict]] = {}
        for e in self._entries:
            if e["user_id"] != user_id or e["week"] != week or "plan" in e:
                continue
            slot = out.setdefault(e["drill"], {}).setdefault(e.get("slot", ""), {"shots": [], "ratings": []})
            if "rating" in e:
                slot["ratings"].append(e["rating"])
            else:
                slot["shots"].append((e["attempts"], e["makes"]))
        return out

    def delete_plan(self, user_id: str, week: str) -> bool:
        """사용자의 그 주 계획을 지운다. 지웠으면 True, 원래 없었으면 False. 기록은 건드리지 않는다."""
        with self._lock:
            keep = [e for e in self._entries if not (e["user_id"] == user_id and e["week"] == week and "plan" in e)]
            removed = len(keep) != len(self._entries)
            if removed:
                self._entries = keep
                self._save()
            return removed

    def count_week_records(self, user_id: str, week: str) -> int:
        """사용자가 그 주에 입력한 기록(슛 세션 + 자기평가) 건수. 계획은 세지 않는다."""
        return sum(1 for e in self._entries if e["user_id"] == user_id and e["week"] == week and "plan" not in e)

    def delete_week_records(self, user_id: str, week: str) -> int:
        """사용자의 그 주 기록을 모두 지우고 지운 건수를 돌려준다. 계획과 다른 주·다른 사용자의 기록은 그대로 둔다."""
        with self._lock:
            keep = [e for e in self._entries if not (e["user_id"] == user_id and e["week"] == week and "plan" not in e)]
            removed = len(self._entries) - len(keep)
            if removed:
                self._entries = keep
                self._save()
            return removed

    def plan_weeks(self, user_id: str) -> list[str]:
        """사용자가 계획을 가진 주 (오래된 주부터)."""
        return sorted({e["week"] for e in self._entries if e["user_id"] == user_id and "plan" in e})

    def get_plan(self, user_id: str, week: str) -> WeeklyPlan | None:
        for e in reversed(self._entries):
            if e["user_id"] == user_id and e["week"] == week and "plan" in e:
                return WeeklyPlan.model_validate(e["plan"])
        return None

    def user_ids(self) -> list[str]:
        """기록이 있는 모든 사용자. 출력 점검에서 다른 사용자의 정보가 섞였는지 볼 때 쓴다."""
        return sorted({e["user_id"] for e in self._entries})

    def has_records(self, user_id: str) -> bool:
        return any(e["user_id"] == user_id for e in self._entries)

    def shots(self, user_id: str, drill: str, week: str) -> list[tuple[int, int]]:
        return [
            (e["attempts"], e["makes"])
            for e in self._entries
            if "attempts" in e and e["user_id"] == user_id and e["drill"] == drill and e["week"] == week
        ]

    def ratings(self, user_id: str, drill: str, week: str) -> list[str]:
        return [
            e["rating"]
            for e in self._entries
            if "rating" in e and e["user_id"] == user_id and e["drill"] == drill and e["week"] == week
        ]

    def past_weeks(self, user_id: str, drill: str, week: str, n: int = 4) -> list[tuple[int, int]]:
        """이번 주 앞의 n주 중 슛 기록이 있는 주의 (시도 합계, 성공 합계). 기록이 없는 주는 뺀다."""
        result = []
        for key in previous_week_keys(week, n):
            sessions = self.shots(user_id, drill, key)
            if sessions:
                result.append((sum(a for a, _ in sessions), sum(m for _, m in sessions)))
        return result


def judge_week(
    store: RecordStore, user_id: str, week: str, plan: WeeklyPlan, catalog: list[Drill]
) -> list[DrillJudgment]:
    """지난주 계획에 있던 연습 메뉴마다 그 주 기록으로 다음 주 난이도를 판정한다."""
    by_name = {d.name: d for d in catalog}
    names = list(dict.fromkeys(pd.name for day in plan.days for pd in day.drills))
    judgments = []
    for name in names:
        drill = by_name.get(name)
        if drill is None:
            continue
        judgments.append(
            judge_drill(
                drill,
                shots=store.shots(user_id, name, week),
                ratings=store.ratings(user_id, name, week),
                past_weeks=store.past_weeks(user_id, name, week),
            )
        )
    return judgments
