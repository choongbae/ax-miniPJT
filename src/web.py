"""웹 화면 전용 엔드포인트 (T26, T27). /query 규약 밖의 추가이며 사용자 허락을 받았다.

모두 로그인이 필요하다(손님은 쓸 수 없다). 화면이 보낸 값은 모델 해석 없이 코드로 검증하고 처리한다.

    POST /plans          입력 폼으로 계획 초안 만들기 (지난주 기록이 있으면 자동 반영). 확정 전까지 저장하지 않는다
    POST /plans/{id}/decision  초안을 확정(confirm)하거나 거절(reject). LangGraph interrupt()로 멈춘 그래프를 이어 간다
    GET  /plans/current  이번 주 계획 다시 보기
    POST /records        연습 기록 한 건 입력 -> 저장하고 난이도 판정
    GET  /records/week   이번 주 계획의 연습 메뉴별 기록과 다음 주 난이도 예고
"""
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Callable, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from src.agent import make_checkpointer, resume_with_decision, start_for_approval
from src.guardrails import check_input
from src.history import basketball_history
from src.knowledge import cards_by_name
from src.models import RATINGS, Drill, WeeklyPlan
from src.orchestrator import judge_last_week
from src.progress import build_progress, build_summary
from src.recommend import field_record_counts, recommend_other_fields
from src.records import judge_week, plan_slots, previous_week_keys, week_key, week_start
from src.retriever import load_menu_docs
from src.tools import DrillJudgment, judge_drill, load_drills, validate_user_input

MAX_GOALS = 5
MAX_GOAL_LENGTH = 40
WEEK_RANGE = 52  # 이번 주 기준 앞뒤로 고를 수 있는 주 수
DRAFT_TTL = timedelta(hours=24)  # 승인 대기 중인 초안은 24시간 안에 확정하지 않으면 버린다


# --- 요청 ---------------------------------------------------------------------------

class PlanRequest(BaseModel):
    is_beginner: bool = False
    position: Literal["가드", "포워드", "센터", "미정"] | None = None
    level: Literal["초급", "중급", "상급"] | None = None
    goals: list[str] = Field(default_factory=list, max_length=MAX_GOALS)
    days_per_week: int
    minutes_per_session: int
    equipment: list[Literal["골대", "콘", "벽"]] = Field(default_factory=list, max_length=3)
    week: str | None = None  # 계획을 만들 주 (예: 2026-W46). 없으면 이번 주


class DecisionIn(BaseModel):
    decision: Literal["confirm", "reject"]


class ShotIn(BaseModel):
    attempts: int
    makes: int


class RecordIn(BaseModel):
    drill: str = Field(min_length=1, max_length=60)
    # 연습 메뉴·주마다 기록은 한 건이다: 슛은 shots 한 쌍, 슛 외는 ratings 하나. 다시 저장하면 그 한 건을 갱신한다.
    shots: list[ShotIn] = Field(default_factory=list, max_length=1)
    ratings: list[Literal["쉬웠음", "적당", "어려웠음"]] = Field(default_factory=list, max_length=1)
    week: str | None = None  # 기록할 주. 없으면 이번 주. 아직 오지 않은 주는 안 된다
    # 기록할 연습 카드(요일, 같은 요일에 같은 메뉴가 또 나오면 '월#2'). 같은 메뉴가 여러 요일에 있어도 카드마다 따로 기록한다.
    # 없으면 그 메뉴의 이 주 기록 전체를 한 건으로 바꾼다(이전 방식).
    slot: str | None = Field(default=None, pattern="^([월화수목금토일](#[2-9])?)?$")


# --- 응답 ---------------------------------------------------------------------------

class JudgmentOut(BaseModel):
    drill: str
    verdict: Literal["하향", "유지", "상향"]
    reason: str
    carry_over: bool = False


class DrillOut(BaseModel):
    name: str
    sets: int
    reps: int
    minutes: int
    purpose: str
    difficulty: str
    is_shooting: bool
    requires: list[str]
    tip: str = ""
    mistake: str = ""
    slot: str = ""  # 이 카드의 기록 슬롯 (요일, 같은 요일에 같은 메뉴가 또 나오면 '월#2')


class DayOut(BaseModel):
    day: str
    total_minutes: int
    drills: list[DrillOut]


class RecommendationOut(BaseModel):
    kept: str  # 상향이지만 올릴 곳이 없어 유지하는 메뉴
    menu: str  # 추천하는 다른 분야 메뉴
    field: str
    difficulty: str
    text: str


class PlanOut(BaseModel):
    week: str
    days: list[DayOut]
    input: dict
    notices: list[str] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)
    last_week: list[JudgmentOut] = Field(default_factory=list)
    recommendations: list[RecommendationOut] = Field(default_factory=list)


class PlanResponse(BaseModel):
    status: Literal["pending", "confirmed", "rejected", "failed"]
    plan_id: str | None = None  # pending일 때만: 확정·거절에 쓰는 초안 ID
    # 이미 계획이 있는 주를 다시 만드는 것이면, 확정할 때 지워지는(pending) 또는 지워진(confirmed) 그 주의 기록 건수
    resets_records: int = 0
    message: str = ""
    violations: list[str] = Field(default_factory=list)
    plan: PlanOut | None = None


class StoryOut(BaseModel):
    id: str
    text: str
    sources: list[str]  # 사실을 확인한 자료 주소


class DeletedOut(BaseModel):
    week: str
    deleted_records: int  # 계획과 함께 지워진 그 주의 기록 건수


class WeeksOut(BaseModel):
    current: str  # 이번 주
    weeks: list[str]  # 계획이 있는 주 (오래된 주부터)


class ProgressWeek(BaseModel):
    week: str
    attempts: int
    makes: int
    rate: float | None  # 성공률(%), 시도가 없으면 None
    enough: bool  # 시도가 20회 이상이라 판정에 쓸 만한 표본인지
    rating_count: int
    rating_avg: float | None  # 쉬웠음 3·적당 2·어려웠음 1점의 평균
    verdicts: dict[str, int]  # 다음 주 난이도 판정 건수 {상향, 유지, 하향}
    drills_recorded: int


class TrendOut(BaseModel):
    status: Literal["up", "flat", "down", "insufficient", "none"]
    recent: float | None
    previous: float | None
    diff: float | None
    text: str


class FieldProgress(BaseModel):
    field: str
    has_data: bool
    weeks: list[ProgressWeek]
    shot_trend: TrendOut
    rating_trend: TrendOut


class SummaryRow(BaseModel):
    field: str
    has_data: bool  # 보이는 기간(최근 8주) 안에 기록이 있는가
    base_has_records: bool  # 기준 주에 기록이 있는가
    attempts: int
    makes: int
    rate: float | None
    enough: bool
    rating_count: int
    rating_avg: float | None
    verdicts: dict[str, int]
    trend_kind: str | None  # 추이가 성공률 기준인지 체감 난이도 기준인지 (기록이 없으면 None)
    trend_status: Literal["up", "flat", "down", "insufficient", "none"]
    trend_text: str
    recorded_weeks: int  # 보이는 기간 중 기록이 있는 주 수
    last_recorded_week: str | None


class RadarAxis(BaseModel):
    field: str
    current: float | None  # 기준 주의 0~100 점수 (기록이 없으면 None)
    previous: float | None  # 비교 주(기준 주의 4주 전)의 0~100 점수
    current_thin: bool  # 표본이 적은 점 (슛 시도 20회 미만, 평가 3건 미만)
    previous_thin: bool


class RadarOut(BaseModel):
    base_week: str
    compare_week: str | None  # 보이는 기간 밖이면 None
    axes: list[RadarAxis]
    axes_with_data: int  # 기준 주에 기록이 있는 분야 수
    min_axes: int  # 차트를 그리는 데 필요한 최소 분야 수


class SummaryOut(BaseModel):
    base_week: str  # 종합표의 기준 주: 기록이 있는 가장 최근 주 (기록이 없으면 이번 주)
    is_current: bool  # 기준 주가 이번 주인가
    fields_with_data: int
    rows: list[SummaryRow]
    radar: RadarOut


class ProgressOut(BaseModel):
    current: str
    weeks: list[str]  # 오래된 주부터, 이번 주까지
    fields: list[FieldProgress]
    summary: SummaryOut


class ShotOut(BaseModel):
    attempts: int
    makes: int


class WeekRecord(BaseModel):
    drill: str
    slot: str = ""  # 이 줄이 가리키는 연습 카드
    day: str = ""
    is_shooting: bool
    shots: list[ShotOut]
    ratings: list[str]
    verdict: Literal["하향", "유지", "상향"]
    reason: str
    carry_over: bool


# --- 도우미 -------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _cards() -> dict[str, list[str]]:
    return cards_by_name(load_menu_docs())


def _split_card(lines: list[str]) -> tuple[str, str]:
    tip = next((l.split(": ", 1)[1] for l in lines if l.startswith("자세 팁: ")), "")
    mistake = next((l.split(": ", 1)[1] for l in lines if l.startswith("자주 하는 실수: ")), "")
    return tip, mistake


def _judgment_out(j: DrillJudgment) -> dict:
    return {"drill": j.drill, "verdict": j.verdict, "reason": j.reason, "carry_over": j.carry_over}


def build_plan_out(week: str, plan: WeeklyPlan, by_name: dict[str, Drill], meta: dict) -> PlanOut:
    cards = _cards()
    slots = iter(plan_slots(plan))  # 카드 순서(요일, 메뉴 순)와 같은 순서
    days = []
    for d in plan.days:
        drills = []
        for pd in d.drills:
            _, slot = next(slots)
            info = by_name.get(pd.name)
            tip, mistake = _split_card(cards.get(pd.name, []))
            drills.append(
                DrillOut(
                    name=pd.name, sets=pd.sets, reps=pd.reps, minutes=pd.minutes, purpose=pd.purpose,
                    difficulty=info.difficulty if info else "", is_shooting=bool(info and info.is_shooting),
                    requires=list(info.requires) if info else [], tip=tip, mistake=mistake, slot=slot,
                )
            )
        days.append(DayOut(day=d.day, total_minutes=d.total_minutes, drills=drills))
    return PlanOut(
        week=week,
        days=days,
        input=meta.get("input", {}),
        notices=meta.get("notices", []),
        history=meta.get("history", []),
        last_week=[JudgmentOut(**j) for j in meta.get("last_week", [])],
        recommendations=[RecommendationOut(**r) for r in meta.get("recommendations", [])],
    )


def add_web_routes(
    app: FastAPI,
    current_user: Callable[[Request], str],
    guest_id: str,
    generate_fn,
    today: Callable[[], date],
    catalog: list[Drill] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> None:
    catalog = catalog if catalog is not None else load_drills()
    by_name = {d.name: d for d in catalog}

    def require_login(request: Request) -> str:
        user = current_user(request)  # 잘못된 토큰이면 여기서 401
        if user == guest_id:
            raise HTTPException(status_code=401, detail="로그인이 필요해요.")
        return user

    def resolve_week(raw: str | None) -> str:
        """화면이 보낸 주 값을 검증한다. 없으면 이번 주. 형식이 틀리거나 이번 주 기준 앞뒤 52주를 벗어나면 422."""
        current = week_key(today())
        if raw is None:
            return current
        start = week_start(raw)
        if start is None or week_key(start) != raw:
            raise HTTPException(status_code=422, detail="주는 2026-W46 같은 형식으로 보내 주세요.")
        if abs((start - week_start(current)).days) > WEEK_RANGE * 7:
            raise HTTPException(status_code=422, detail=f"이번 주에서 앞뒤 {WEEK_RANGE}주 안의 주만 고를 수 있어요.")
        return raw

    def checkpointer():
        if getattr(app.state, "checkpointer", None) is None:  # 처음 필요할 때 만든다 (DB 파일 옆에 둔다)
            app.state.checkpointer = make_checkpointer(app.state.store.path.with_name("checkpoints.db"))
        return app.state.checkpointer

    def drop_draft(plan_id: str) -> None:
        app.state.store.delete_draft(plan_id)
        try:
            checkpointer().delete_thread(plan_id)
        except Exception:  # 정리 실패가 사용자 요청을 막으면 안 된다
            pass

    def plan_meta(state, user_id: str, week: str) -> dict:
        user = state["user"]
        in_plan = {pd.name for day in state["plan"].days for pd in day.drills}
        counts = field_record_counts(app.state.store, user_id, week, catalog)
        return {
            "input": {
                "position": user.position, "level": user.level, "is_beginner": user.is_beginner, "goals": user.goals,
                "days_per_week": user.days_per_week, "minutes_per_session": user.minutes_per_session,
                "equipment": user.equipment,
            },
            "notices": state.get("notices", []),
            "history": state.get("history", []),
            "last_week": [_judgment_out(j) for j in state.get("judgments", [])],
            # 올릴 곳이 없는 상향은 그 메뉴를 유지하고 다른 분야를 추천한다 (규칙, 모델 아님)
            "recommendations": [r.as_dict() for r in recommend_other_fields(state.get("judgments"), catalog, user, counts, in_plan)],
        }

    # --- 계획 ---------------------------------------------------------------------
    @app.post("/plans", response_model=PlanResponse)
    def make_plan(body: PlanRequest, request: Request) -> PlanResponse:
        user_id = require_login(request)
        goals = [g.strip() for g in body.goals if g.strip()]
        if any(len(g) > MAX_GOAL_LENGTH for g in goals):
            raise HTTPException(status_code=422, detail=f"약점·목표는 하나에 {MAX_GOAL_LENGTH}자까지 쓸 수 있어요.")
        blocked = check_input(" ".join(goals)) if goals else None
        if blocked is not None:  # 자유 입력으로 지시를 바꾸려는 시도도 막는다
            raise HTTPException(status_code=422, detail=blocked.message)

        raw = {
            "is_beginner": body.is_beginner,
            "goals": goals,
            "days_per_week": body.days_per_week,
            "minutes_per_session": body.minutes_per_session,
            "equipment": list(body.equipment),
        }
        if not body.is_beginner:
            raw["level"], raw["position"] = body.level, body.position or "미정"
        user, errors = validate_user_input(raw)
        if errors:
            raise HTTPException(status_code=422, detail="\n".join(errors))

        week = resolve_week(body.week)
        trace: list[dict] = []
        _, judgments = judge_last_week(user_id, app.state.store, catalog, week, trace)
        plan_id, replaced = app.state.store.create_draft(user_id, week, now().isoformat())
        for old_id in replaced:  # 사용자당 대기 초안은 1개: 이전 초안은 버린다
            try:
                checkpointer().delete_thread(old_id)
            except Exception:
                pass
        try:
            state = start_for_approval(user, catalog, generate_fn, judgments or None, app.state.retriever, checkpointer(), plan_id)
        except Exception:
            drop_draft(plan_id)
            raise
        if state.get("status") != "ok":
            drop_draft(plan_id)
            return PlanResponse(
                status="failed",
                message="입력하신 조건에 맞는 연습 계획을 만들지 못했어요. 연습 시간이나 장비 조건을 바꿔서 다시 시도해 주세요.",
                violations=state.get("violations", []),
            )
        replaces = app.state.store.get_plan(user_id, week) is not None  # 계획이 없던 주에 미리 넣은 기록은 지우지 않는다
        resets = app.state.store.count_week_records(user_id, week) if replaces else 0
        return PlanResponse(
            status="pending", plan_id=plan_id, resets_records=resets,
            plan=build_plan_out(week, state["plan"], by_name, plan_meta(state, user_id, week)),
        )

    @app.post("/plans/{plan_id}/decision", response_model=PlanResponse)
    def decide_plan(plan_id: str, body: DecisionIn, request: Request) -> PlanResponse:
        user_id = require_login(request)
        draft = app.state.store.get_draft(plan_id)
        if draft is None or draft["user_id"] != user_id:  # 남의 초안이나 없는 초안은 구별하지 않는다
            raise HTTPException(status_code=404, detail="계획 초안을 찾을 수 없어요. 다시 만들어 주세요.")
        if now() - datetime.fromisoformat(draft["created_at"]) > DRAFT_TTL:
            drop_draft(plan_id)
            raise HTTPException(status_code=410, detail="계획 초안이 만료됐어요(24시간). 다시 만들어 주세요.")
        state = resume_with_decision(body.decision, checkpointer(), plan_id)
        drop_draft(plan_id)
        if state.get("approval") != "confirm":
            return PlanResponse(status="rejected", message="이 계획은 저장하지 않았어요.")
        store, week = app.state.store, draft["week"]
        meta = plan_meta(state, user_id, week)
        replaces = store.get_plan(user_id, week) is not None
        store.save_plan(user_id, week, state["plan"], meta)
        removed = store.delete_week_records(user_id, week) if replaces else 0  # 교체한 주의 수행 기록은 새 계획과 맞지 않아 초기화한다
        return PlanResponse(
            status="confirmed", resets_records=removed, plan=build_plan_out(week, state["plan"], by_name, meta)
        )

    @app.get("/story", response_model=StoryOut)
    def story(request: Request) -> StoryOut:
        """오늘의 농구 이야기 1건. 모델을 부르지 않고 확인된 이야기 목록(data/history.json)에서만 고른다."""
        require_login(request)
        result = basketball_history()
        if not result.stories:
            raise HTTPException(status_code=404, detail="보여 줄 이야기가 없어요.")
        return StoryOut(id=result.ids[0], text=result.stories[0], sources=result.sources)

    @app.delete("/plans", response_model=DeletedOut)
    def delete_plan(request: Request, week: str = Query(...)) -> DeletedOut:
        """선택한 주의 계획을 지운다. 그 주의 수행 기록도 함께 지우고(되돌릴 수 없다), 그 주의 승인 대기 초안도 정리한다.

        주를 반드시 적어야 한다(빠뜨려서 이번 주가 지워지는 일이 없게)."""
        user_id = require_login(request)
        week = resolve_week(week)
        store = app.state.store
        if store.get_plan(user_id, week) is None:
            raise HTTPException(status_code=404, detail="이 주에는 삭제할 계획이 없어요.")
        for draft_id in store.delete_drafts(user_id, week):
            try:
                checkpointer().delete_thread(draft_id)
            except Exception:  # 정리 실패가 삭제를 막으면 안 된다
                pass
        store.delete_plan(user_id, week)
        return DeletedOut(week=week, deleted_records=store.delete_week_records(user_id, week))

    @app.get("/plans/weeks", response_model=WeeksOut)
    def plan_weeks(request: Request) -> WeeksOut:
        user_id = require_login(request)
        return WeeksOut(current=week_key(today()), weeks=app.state.store.plan_weeks(user_id))

    @app.get("/plans/current", response_model=PlanOut | None)
    def current_plan(request: Request, week: str | None = None) -> PlanOut | None:
        user_id = require_login(request)
        week = resolve_week(week)
        plan = app.state.store.get_plan(user_id, week)
        if plan is None:
            return None
        return build_plan_out(week, plan, by_name, app.state.store.get_plan_meta(user_id, week))

    # --- 현황 ---------------------------------------------------------------------
    @app.get("/progress", response_model=ProgressOut)
    def progress(request: Request, weeks: int = Query(default=8, ge=4, le=26)) -> ProgressOut:
        user_id = require_login(request)
        current = week_key(today())
        shown = list(reversed(previous_week_keys(current, weeks - 1))) + [current]  # 오래된 주부터 이번 주까지
        wanted = shown + previous_week_keys(shown[0], 4)  # 앞 4주는 난이도 판정의 과거 기록 보정에 쓴다
        records = app.state.store.records_for_weeks(user_id, wanted)
        fields = build_progress(records, catalog, shown)
        return ProgressOut(current=current, weeks=shown, fields=fields, summary=build_summary(fields, shown))

    # --- 기록 ---------------------------------------------------------------------
    @app.post("/records", response_model=JudgmentOut)
    def add_record(body: RecordIn, request: Request) -> JudgmentOut:
        user_id = require_login(request)
        drill = by_name.get(body.drill)
        if drill is None:
            raise HTTPException(status_code=422, detail="알 수 없는 연습 메뉴예요.")
        if bool(body.shots) == bool(body.ratings):
            raise HTTPException(status_code=422, detail="슛은 시도·성공 횟수를, 슛 외 연습은 평가를 하나만 입력해 주세요.")
        if drill.is_shooting and body.ratings or not drill.is_shooting and body.shots:
            raise HTTPException(status_code=422, detail="슛 연습은 시도·성공 횟수, 슛 외 연습은 '쉬웠음/적당/어려웠음' 평가로 입력해 주세요.")

        week = resolve_week(body.week)
        if week_start(week) > week_start(week_key(today())):
            raise HTTPException(status_code=422, detail="아직 오지 않은 주예요. 연습한 뒤에 기록해 주세요.")
        store = app.state.store
        slot, absorb = body.slot or "", False
        if slot:
            plan = store.get_plan(user_id, week)
            if plan is not None:  # 계획이 있으면 그 계획의 카드여야 한다
                cards_of_drill = [s for name, s in plan_slots(plan) if name == drill.name]
                if slot not in cards_of_drill:
                    raise HTTPException(status_code=422, detail="이 주 계획에 없는 연습 카드예요.")
                absorb = slot == cards_of_drill[0]  # 슬롯이 없던 예전 기록은 첫 카드에 붙어 있다
        if body.shots:
            errors = store.replace_record(
                user_id, drill.name, week, shot=(body.shots[0].attempts, body.shots[0].makes), slot=slot, absorb_legacy=absorb
            )
        else:
            errors = store.replace_record(user_id, drill.name, week, rating=body.ratings[0], slot=slot, absorb_legacy=absorb)
        if errors:
            raise HTTPException(status_code=422, detail="\n".join(dict.fromkeys(errors)))
        j = judge_drill(
            drill,
            shots=store.shots(user_id, drill.name, week),
            ratings=store.ratings(user_id, drill.name, week),
            past_weeks=store.past_weeks(user_id, drill.name, week),
        )
        return JudgmentOut(**_judgment_out(j))

    @app.get("/records/week", response_model=list[WeekRecord])
    def week_records(request: Request, week: str | None = None) -> list[WeekRecord]:
        user_id = require_login(request)
        store, week = app.state.store, resolve_week(week)
        plan = store.get_plan(user_id, week)
        if plan is None:
            return []
        judgments = {j.drill: j for j in judge_week(store, user_id, week, plan, catalog)}  # 난이도 판정은 그 메뉴의 모든 카드 기록을 합쳐서
        per_card = store.slot_records(user_id, week)
        cards = plan_slots(plan)
        first: dict[str, str] = {}
        for name, slot in cards:
            first.setdefault(name, slot)
        days = [day.day for day in plan.days for _ in day.drills]
        out = []
        for (name, slot), day in zip(cards, days):
            j, drill = judgments.get(name), by_name.get(name)
            if j is None or drill is None:
                continue
            mine = per_card.get(name, {}).get(slot, {"shots": [], "ratings": []})
            legacy = per_card.get(name, {}).get("", {"shots": [], "ratings": []}) if slot == first[name] else {"shots": [], "ratings": []}
            out.append(
                WeekRecord(
                    drill=name,
                    slot=slot,
                    day=day,
                    is_shooting=drill.is_shooting,
                    shots=[ShotOut(attempts=a, makes=m) for a, m in legacy["shots"] + mine["shots"]],
                    ratings=legacy["ratings"] + mine["ratings"],
                    verdict=j.verdict,
                    reason=j.reason,
                    carry_over=j.carry_over,
                )
            )
        return out
