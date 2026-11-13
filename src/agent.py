"""메인 에이전트.

계획 생성 체인(LCEL + Pydantic 구조화 출력)과, 생성 -> 검증 -> (위반 시) 재생성 그래프(LangGraph).
규칙 검증은 LLM이 아니라 src/tools.py의 코드가 한다.
"""
import logging
import re
import sys
from typing import Callable, TypedDict

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from src.adjust import adjustment_candidates, floor_notices, format_judgments, validate_adjustments
from src.history import basketball_history
from src.knowledge import cards_by_name
from src.llm import get_fallback_llms, get_llm
from src.models import Drill, UserInput, WeeklyPlan
from src.tools import DrillJudgment, drop_unsupported_goal_menus, equipment_notices, load_drills, validate_goal_claims, validate_plan, validate_user_input
from src.tracing import traced

logger = logging.getLogger(__name__)

MAX_RETRIES = 2  # 검증에 실패하면 최대 2번까지 다시 만든다 (처음 생성 포함 최대 3번)

SYSTEM = """당신은 혼자 연습하는 취미 농구 선수를 위한 연습 계획 코치입니다.
사용자 조건에 맞는 1주 연습 계획을 만듭니다. 아래 규칙을 반드시 지키세요.

1. 연습일 수는 사용자가 말한 주 연습일을 넘기지 않습니다.
2. 하루에 배정한 연습 메뉴 시간(분)의 합은 회당 연습 시간을 넘기지 않습니다. 가능하면 그 시간에 가깝게 채웁니다.
3. 연습 메뉴는 아래 '사용 가능한 연습 메뉴' 목록에 있는 것만, 이름을 한 글자도 바꾸지 않고 사용합니다.
4. 난이도는 사용자의 실력 수준에 맞는 연습 메뉴를 우선 사용하고, 부족하면 한 단계 낮은 연습 메뉴를 씁니다.
5. 사용자의 약점·목표와 관련된 연습 메뉴를 포함합니다.
6. 각 연습 메뉴에는 세트 수, 반복 수, 소요 시간(분), 목적을 적습니다. 목적은 연습 메뉴 목록의 목적을 바탕으로 사용자에게 맞게 쉽게 씁니다.
7. 요일 이름은 월, 화, 수, 목, 금, 토, 일 중에서 연습일 수만큼 골라 씁니다.
8. '지난주 결과에 따른 난이도 조정'이 주어지면 규칙 4보다 우선해서 그대로 따릅니다."""

HUMAN = """[사용자 조건]
- 포지션: {position}
- 실력 수준: {level}
- 약점·목표: {goals}
- 주 연습일: {days}일
- 회당 연습 시간: {minutes}분
- 있는 장소·장비: {equipment}

[사용 가능한 연습 메뉴]
{drills}
{beginner}{adjustments}{violations}
위 조건에 맞는 1주 연습 계획을 만들어 주세요."""

prompt = ChatPromptTemplate.from_messages([("system", SYSTEM), ("human", HUMAN)])


BEGINNER_NOTE = (
    "\n[초보자 옵션] 농구를 처음 시작한 사람입니다. 위 목록의 초급 연습 메뉴만 사용하세요. "
    "슛 폼, 볼 핸들링, 레이업 기초 같은 기본기를 장소·장비가 허락하는 범위에서 고르게 섞고, "
    "한 가지 연습 메뉴만 반복하지 마세요. 연습 메뉴의 목적 설명은 전문 용어를 풀어서 "
    "처음 하는 사람도 이해할 수 있는 쉬운 말로 쓰세요.\n"
)


def available_drills(user: UserInput, catalog: list[Drill]) -> list[Drill]:
    """사용자가 가진 장소·장비로 할 수 있는 연습 메뉴만 남긴다. 초보자는 초급 메뉴만 남긴다."""
    owned = set(user.equipment)
    drills = drop_unsupported_goal_menus([d for d in catalog if set(d.requires) <= owned], user, catalog)
    if user.is_beginner:
        drills = [d for d in drills if d.difficulty == "초급"]
    return drills


def format_drills(drills: list[Drill]) -> str:
    return "\n".join(
        f"- {d.name} | 난이도: {d.difficulty} | {'슛' if d.is_shooting else '슛 외'} | 목적: {d.purpose}"
        for d in drills
    )


RETRIEVE_K = 12  # 검색해서 프롬프트에 줄 연습 메뉴 수

# 검색 후보로 주는 난이도: 사용자 수준과 한 단계 아래. 더 어려운 메뉴는 지난주 결과가 상향일 때만 판정 후보로 들어간다.
LEVELS_FOR = {"초급": ["초급"], "중급": ["초급", "중급"], "상급": ["중급", "상급"]}


def build_query(user: UserInput) -> str:
    """사용자 조건을 연습 메뉴 문서 검색 질의로 만든다."""
    parts = [f"{user.level} 수준"]
    if user.position != "미정":
        parts.append(f"{user.position} 포지션")
    if user.goals:
        parts.append("약점·목표: " + ", ".join(user.goals))
    if user.is_beginner:
        parts.append("농구를 처음 시작해서 기본기를 배우고 싶다")
    return " ".join(parts) + " 연습 메뉴"


def select_menus(
    user: UserInput,
    catalog: list[Drill],
    retriever,
    judgments: list[DrillJudgment] | None = None,
    k: int = RETRIEVE_K,
) -> tuple[list[Drill], list[dict]]:
    """검색으로 이번 계획에 쓸 연습 메뉴를 고른다. (연습 메뉴 목록, API 응답용 contexts)를 돌려준다.

    검색 결과에 더해, 지난주 판정에서 꼭 필요한 메뉴(기록 없던 메뉴, 하향·상향 후보)는 검색에 안 걸려도 포함한다.
    사용자가 가진 장소·장비로 할 수 없는 메뉴와, 초보자에게 초급이 아닌 메뉴는 넣지 않는다.
    """
    allowed = {d.name: d for d in available_drills(user, catalog)}
    results = retriever.search(
        build_query(user),
        equipment=user.equipment,
        levels=["초급"] if user.is_beginner else LEVELS_FOR[user.level],
        k=k,
        kinds=["menu"],  # 계획에는 연습 메뉴 문서만 쓴다 (용어·원리 같은 안내 문서는 제외)
    )
    menus: list[Drill] = []

    def add(name: str) -> None:
        if name in allowed and allowed[name] not in menus:
            menus.append(allowed[name])

    for r in results:
        add(r.doc.name)
    by_name = {d.name: d for d in catalog}
    for j in judgments or []:
        drill = by_name.get(j.drill)
        if drill is None:
            continue
        add(j.drill)
        for c in adjustment_candidates(drill, j.verdict, catalog, user):
            add(c.name)
    contexts = [{"doc_id": r.doc.doc_id, "text": r.doc.text} for r in results]
    return menus, contexts


def build_prompt_values(
    user: UserInput,
    catalog: list[Drill],
    violations: list[str] | None = None,
    judgments: list[DrillJudgment] | None = None,
    menus: list[Drill] | None = None,
) -> dict:
    """프롬프트에 들어갈 값. violations가 있으면 이전 계획의 위반 사유로, judgments가 있으면 지난주 판정으로 넣는다.

    menus는 검색으로 고른 연습 메뉴. 없으면 사용자가 할 수 있는 전체 메뉴를 쓴다."""
    feedback = ""
    if violations:
        feedback = "\n[이전 계획의 문제점 - 반드시 고쳐서 다시 만드세요]\n" + "\n".join(
            f"- {v}" for v in violations
        )
    return {
        "position": user.position,
        "level": user.level,
        "goals": ", ".join(user.goals) or "없음",
        "days": user.days_per_week,
        "minutes": user.minutes_per_session,
        "equipment": ", ".join(user.equipment) or "없음 (공만 있음)",
        "drills": format_drills(menus if menus is not None else available_drills(user, catalog)),
        "beginner": BEGINNER_NOTE if user.is_beginner else "",
        "adjustments": format_judgments(judgments, catalog, user),
        "violations": feedback,
    }


def generate_plan(
    user: UserInput,
    catalog: list[Drill],
    violations: list[str] | None = None,
    judgments: list[DrillJudgment] | None = None,
    llm=None,
    menus: list[Drill] | None = None,
) -> WeeklyPlan:
    """LLM으로 1주 계획을 만든다 (구조화 출력). menus는 검색으로 고른 연습 메뉴.

    llm을 주지 않으면 기본 모델을 쓰고, 그 모델이 실패하면(일일 한도 초과, 권한, 종료 등) 대체 모델로 이어서 시도한다.
    """
    if llm is not None:
        chain = prompt | llm.with_structured_output(WeeklyPlan)
    else:
        chain = prompt | get_llm().with_structured_output(WeeklyPlan)
        fallbacks = [prompt | m.with_structured_output(WeeklyPlan) for m in get_fallback_llms()]
        if fallbacks:
            chain = chain.with_fallbacks(fallbacks)
    return chain.invoke(build_prompt_values(user, catalog, violations, judgments, menus))


class AgentState(TypedDict, total=False):
    user: UserInput
    catalog: list[Drill]
    plan: WeeklyPlan | None
    judgments: list[DrillJudgment]  # 지난주 기록으로 판정한 연습 메뉴별 결과
    menus: list[Drill]  # 검색으로 고른, 이번 계획에 쓸 연습 메뉴
    contexts: list[dict]  # 검색한 문서 (doc_id, text). API 응답의 contexts가 된다.
    violations: list[str]
    attempts: int
    status: str  # "ok" 또는 "failed"
    approval: str  # 사용자의 승인 결정: "confirm" 또는 "reject" (승인 단계를 쓸 때만)
    notices: list[str]  # 장비 때문에 빠진 목표 안내
    cards: dict  # 계획의 연습 메뉴별 카드 요약 {이름: [줄, ...]}
    history: list[str]  # 계획 화면에 보여 줄 농구 역사 이야기
    log: list[str]
    trace: list[dict]  # 도구 호출 기록 [{"step", "input", "output"}] (API 응답의 trace가 된다)


GenerateFn = Callable[..., WeeklyPlan]  # (user, catalog, violations, judgments, menus=...) -> 계획


def _trace(state: AgentState, step: str, step_input: str, step_output: str) -> list[dict]:
    """state의 trace에 한 단계를 덧붙인 새 목록. 값은 모두 문자열이다."""
    return state.get("trace", []) + [{"step": step, "input": step_input, "output": step_output}]


def build_graph(generate_fn: GenerateFn = generate_plan, retriever=None, approval: bool = False, checkpointer=None):
    """검색 -> 생성 -> 검증 -> (위반 시 재생성 | 종료) 그래프. generate_fn과 retriever는 테스트에서 바꿔 끼울 수 있다.

    approval=True이면 검증을 통과한 계획에 대해 interrupt()로 멈추고 사용자의 결정(confirm/reject)을 기다린다.
    멈춘 상태는 checkpointer에 저장되므로 서버를 다시 켜도 이어 갈 수 있다."""

    def retrieve_node(state: AgentState) -> dict:
        user, catalog = state["user"], state["catalog"]
        if retriever is None:
            menus, contexts, entry = available_drills(user, catalog), [], "검색 없이 가능한 연습 메뉴 전체 사용"
        else:
            try:
                menus, contexts = select_menus(user, catalog, retriever, state.get("judgments"))
                entry = f"검색: {len(contexts)}개 문서 -> 연습 메뉴 {len(menus)}개 선택"
            except Exception as e:  # 검색이 실패해도 계획은 만들 수 있게 전체 목록으로 대신한다
                menus, contexts = available_drills(user, catalog), []
                entry = f"검색 실패({type(e).__name__})로 가능한 연습 메뉴 전체 사용"
        logger.info(entry)
        return {
            "menus": menus,
            "contexts": contexts,
            "log": state.get("log", []) + [entry],
            "trace": _trace(
                state,
                "search_drills",
                build_query(user),
                f"{entry}: " + ", ".join(m.name for m in menus),
            ),
        }

    def generate_node(state: AgentState) -> dict:
        attempts = state.get("attempts", 0) + 1
        previous = state.get("violations") or None
        judgments = state.get("judgments") or None
        plan = generate_fn(state["user"], state["catalog"], previous, judgments, menus=state.get("menus"))
        entry = f"시도 {attempts}: 계획 생성" + (" (이전 위반 사유 반영)" if previous else "")
        logger.info(entry)
        summary = f"{len(plan.days)}일 계획: " + " / ".join(
            f"{d.day} " + ", ".join(x.name for x in d.drills) for d in plan.days
        )
        return {
            "plan": plan,
            "attempts": attempts,
            "log": state.get("log", []) + [entry],
            "trace": _trace(state, "generate_plan", entry + (f" | 이전 위반: {'; '.join(previous)}" if previous else ""), summary),
        }

    def validate_node(state: AgentState) -> dict:
        violations = (
            validate_plan(state["plan"], state["user"], state["catalog"])
            + validate_adjustments(state["plan"], state.get("judgments"), state["catalog"], state["user"])
            + validate_goal_claims(state["plan"], state["user"], state["catalog"])
        )
        entry = f"시도 {state['attempts']}: 검증 " + (
            "통과" if not violations else f"위반 {len(violations)}건 - " + " / ".join(violations)
        )
        logger.info(entry)
        return {
            "violations": violations,
            "log": state.get("log", []) + [entry],
            "trace": _trace(
                state,
                "validate_plan",
                f"시도 {state['attempts']}의 계획",
                "통과" if not violations else "; ".join(violations),
            ),
        }

    def route(state: AgentState) -> str:
        if not state["violations"]:
            return "done"
        if state["attempts"] > MAX_RETRIES:
            return "done"
        return "retry"

    def finish_node(state: AgentState) -> dict:
        ok = not state["violations"]
        entry = "종료: 검증을 통과한 계획입니다." if ok else (
            f"종료: {state['attempts']}번 시도했지만 규칙을 지키는 계획을 만들지 못했습니다."
        )
        logger.info(entry)
        cards: dict = {}
        history: list[str] = []
        if ok:
            history = basketball_history().stories  # 계획 화면에는 확인된 이야기 1건 (모델 호출 없음)
            from src.retriever import load_menu_docs

            all_cards = cards_by_name(load_menu_docs())
            names = dict.fromkeys(pd.name for day in state["plan"].days for pd in day.drills)
            cards = {n: all_cards[n] for n in names if n in all_cards}
        return {
            "status": "ok" if ok else "failed",
            "notices": equipment_notices(state["user"], state["catalog"])
            + (floor_notices(state.get("judgments"), state["catalog"], state["user"]) if ok else []),
            "cards": cards,
            "history": history,
            "log": state.get("log", []) + [entry],
        }

    def approve_node(state: AgentState) -> dict:
        decision = interrupt({"kind": "plan_approval", "attempts": state["attempts"]})  # 여기서 멈추고, 재개 값이 decision이 된다
        decision = "confirm" if decision == "confirm" else "reject"
        return {
            "approval": decision,
            "trace": _trace(state, "approve_plan", "사용자 확인", "확정" if decision == "confirm" else "거절"),
        }

    def after_finish(state: AgentState) -> str:
        return "approve" if approval and state["status"] == "ok" else "end"

    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_node("validate", validate_node)
    graph.add_node("finish", finish_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", "validate")
    graph.add_conditional_edges("validate", route, {"retry": "generate", "done": "finish"})
    if approval:
        graph.add_node("approve", approve_node)
        graph.add_conditional_edges("finish", after_finish, {"approve": "approve", "end": END})
        graph.add_edge("approve", END)
    else:
        graph.add_edge("finish", END)
    return graph.compile(checkpointer=checkpointer)


@traced("plan_graph", "chain", keep=("user", "judgments"))
def run_agent(
    user: UserInput,
    catalog: list[Drill] | None = None,
    generate_fn: GenerateFn = generate_plan,
    judgments: list[DrillJudgment] | None = None,
    retriever=None,
) -> AgentState:
    """입력(과 지난주 판정)으로 1주 계획을 만든다. retriever(MenuRetriever)를 주면 연습 메뉴를 검색으로 고른다.

    status가 "failed"이면 plan은 규칙을 어긴 계획이므로 쓰면 안 된다."""
    state: AgentState = {
        "user": user,
        "catalog": catalog if catalog is not None else load_drills(),
        "judgments": judgments or [],
        "attempts": 0,
        "violations": [],
        "log": [],
        "trace": [],
    }
    return build_graph(generate_fn, retriever).invoke(state)


def _initial_state(user, catalog, judgments) -> AgentState:
    return {
        "user": user,
        "catalog": catalog if catalog is not None else load_drills(),
        "judgments": judgments or [],
        "attempts": 0,
        "violations": [],
        "log": [],
        "trace": [],
    }


def make_checkpointer(path):
    """멈춘 계획(승인 대기)을 저장하는 SQLite 체크포인터. 저장하는 우리 타입만 명시적으로 허용한다."""
    import sqlite3

    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
    from langgraph.checkpoint.sqlite import SqliteSaver

    allowed = [("src.models", "UserInput"), ("src.models", "Drill"), ("src.models", "WeeklyPlan"),
               ("src.models", "DayPlan"), ("src.models", "PlannedDrill"), ("src.tools", "DrillJudgment")]
    return SqliteSaver(sqlite3.connect(path, check_same_thread=False), serde=JsonPlusSerializer(allowed_msgpack_modules=allowed))


@traced("plan_graph_draft", "chain", keep=("user", "judgments", "thread_id"))
def start_for_approval(user, catalog, generate_fn, judgments, retriever, checkpointer, thread_id: str) -> AgentState:
    """계획을 만들고, 검증을 통과하면 사용자 승인을 기다리며 멈춘다. 돌려주는 state에 plan(초안)이 들어 있다.

    status가 "failed"이면 멈추지 않고 끝난 것이다(승인할 계획이 없다)."""
    graph = build_graph(generate_fn, retriever, approval=True, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    graph.invoke(_initial_state(user, catalog, judgments), config)
    return graph.get_state(config).values


@traced("plan_graph_decision", "chain", keep=("decision", "thread_id"))
def resume_with_decision(decision: str, checkpointer, thread_id: str) -> AgentState:
    """멈춘 계획에 사용자의 결정("confirm" 또는 "reject")을 넣어 이어서 끝낸다."""
    graph = build_graph(approval=True, checkpointer=checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    graph.invoke(Command(resume=decision), config)
    return graph.get_state(config).values


# ---------------------------------------------------------------------------
# 최종 답변 포맷과 CLI 진입점 (python -m src.agent)
# ---------------------------------------------------------------------------

def format_result(state: AgentState) -> str:
    """에이전트 결과를 사용자가 읽는 문장으로 만든다. 실패한 계획은 보여 주지 않는다."""
    user = state["user"]
    if state["status"] != "ok":
        lines = ["입력하신 조건에 맞는 연습 계획을 만들지 못했습니다."]
        lines += [f"- {v}" for v in state.get("violations", [])]
        lines.append("연습 시간이나 장비 조건을 바꿔서 다시 시도해 주세요.")
        return "\n".join(lines)

    lines = [
        f"농구 연습 계획 (주 {user.days_per_week}일 · 회당 {user.minutes_per_session}분)",
        f"포지션: {user.position} | 수준: {user.level} | 목표: {', '.join(user.goals) or '없음'}",
    ]
    lines += [f"안내: {n}" for n in state.get("notices", [])]
    for day in state["plan"].days:
        lines += ["", f"[{day.day}] 총 {day.total_minutes}분"]
        for i, d in enumerate(day.drills, 1):
            lines.append(f"  {i}. {d.name} - {d.sets}세트 × {d.reps}회 ({d.minutes}분)")
            lines.append(f"     목적: {d.purpose}")
            lines += [f"     {c}" for c in state.get("cards", {}).get(d.name, [])]
    if state.get("history"):
        lines += ["", "[오늘의 농구 이야기]", *state["history"]]
    return "\n".join(lines)


def split_items(text: str) -> list[str]:
    """쉼표로 구분한 입력을 목록으로 바꾼다. '없음'이나 빈 입력은 빈 목록이다."""
    items = [t.strip() for t in re.split(r"[,，;/]", text) if t.strip()]
    return [] if items == ["없음"] else items


YES_ANSWERS = {"예", "네", "응", "y", "yes", "ㅇ"}


def collect_input(input_fn=input, first_time: bool = False) -> dict:
    """사용자 입력을 받는다. 첫 사용자(기록 없음)에게만 초보자인지 묻고, 초보자면 포지션·수준은 묻지 않는다."""
    raw: dict = {}
    if first_time:
        answer = input_fn("농구를 처음 시작하는 사람인가요? (예/아니오): ").strip().lower()
        raw["is_beginner"] = answer in YES_ANSWERS
    if not raw.get("is_beginner"):
        raw["position"] = input_fn("포지션 (가드/포워드/센터): ").strip()
        raw["level"] = input_fn("실력 수준 (초급/중급/상급): ").strip()
    raw["goals"] = split_items(input_fn("약점·목표 (쉼표로 구분, 없으면 엔터): "))
    raw["days_per_week"] = input_fn("주 연습일 (1~7): ").strip()
    raw["minutes_per_session"] = input_fn("회당 연습 시간(분): ").strip()
    raw["equipment"] = split_items(input_fn("있는 장소·장비 (예: 골대, 콘, 벽 / 공만 있으면 엔터): "))
    return raw


def main(input_fn=input, run=run_agent, out=print, store=None, user_id: str = "default") -> int:
    """입력 -> 검증 -> 계획 생성 -> 출력. 성공 0, 입력 오류나 생성 실패 1.

    store(RecordStore)를 주면 그 사용자에게 기록이 없을 때(첫 사용자)만 초보자인지 묻는다.
    """
    first_time = store is not None and not store.has_records(user_id)
    user, errors = validate_user_input(collect_input(input_fn, first_time))
    if errors:
        out("입력을 확인해 주세요.")
        for e in errors:
            out(f"- {e}")
        return 1
    state = run(user)
    out("")
    out(format_result(state))
    return 0 if state["status"] == "ok" else 1


if __name__ == "__main__":
    # 파이프로 입력을 넣을 때 한글이 깨지지 않도록 UTF-8로 고정한다.
    if not sys.stdin.isatty():
        sys.stdin.reconfigure(encoding="utf-8")
    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")

    import argparse

    from src.records import RecordStore
    from src.retriever import MenuRetriever

    parser = argparse.ArgumentParser(description="농구 연습 계획 Agent")
    parser.add_argument("--user", default="default", help="기록을 구분하는 사용자 이름 (기본값: default)")
    args = parser.parse_args()
    retriever = MenuRetriever()  # 연습 메뉴 문서가 바뀌었을 때만 색인을 다시 만든다
    raise SystemExit(
        main(
            run=lambda user: run_agent(user, retriever=retriever),
            store=RecordStore(),
            user_id=args.user,
        )
    )
