"""질문 -> 도구 선택 -> 답변 흐름 테스트. 요청 분석(LLM)과 계획 생성(LLM)은 가짜로 바꿔서 흐름만 확인한다."""
from datetime import date
from types import SimpleNamespace

import pytest

from src.models import WeeklyPlan
from src.orchestrator import (
    ParsedRequest,
    PastWeek,
    Report,
    SessionEntry,
    answer_question,
    map_drill,
)
from src.records import RecordStore
from src.retriever import SearchResult, load_all_docs
from src.tools import load_drills

CATALOG = load_drills()
DOCS = {d.doc_id: d for d in load_all_docs()}
TODAY = date(2026, 11, 12)  # 2026-W46


def steps(resp):
    return [t["step"] for t in resp.trace if t["step"] != "output_check"]


@pytest.fixture
def store(tmp_path):
    return RecordStore(tmp_path / "records.json")


def ask(question, parsed, store, **kw):
    return answer_question(question, store=store, catalog=CATALOG, parse_fn=lambda q: parsed, today=TODAY, **kw)


def plan_of(*names, minutes=10):
    def fake(user, catalog, violations, judgments=None, menus=None):
        drills = [{"name": n, "sets": 3, "reps": 10, "minutes": minutes, "purpose": "p"} for n in names]
        return WeeklyPlan.model_validate({"days": [{"day": "월", "drills": drills}]})

    return fake


class StubKnowledgeRetriever:
    """지식 질문용 검색기: search_hybrid가 준비된 결과를 돌려준다."""

    def __init__(self, doc_ids):
        self.doc_ids = doc_ids
        self.queries = []

    def search_hybrid(self, query, k=3, max_distance=None, margin=None, kinds=None):
        self.queries.append(query)
        return [SearchResult(DOCS[i], 0.5) for i in self.doc_ids]


class StubLLM:
    def __init__(self, text):
        self.text = text

    def invoke(self, messages):
        return SimpleNamespace(content=self.text)


# --- 지식 · 그 밖의 질문 -----------------------------------------------------------------

def test_case7_knowledge_question_calls_retrieve_then_drill_knowledge(store):
    retriever = StubKnowledgeRetriever(["three-point-catch-and-shoot"])
    resp = answer_question(
        "캐치앤슛 연습할 때 자주 하는 실수가 뭐야?",
        retriever=retriever,
        store=store,
        parse_fn=lambda q: ParsedRequest(intent="knowledge"),
        knowledge_llm=StubLLM("공을 받고 한 번 내려놓았다가 쏘는 것이 흔한 실수입니다."),
    )
    assert steps(resp) == ["parse_question", "retrieve", "drill_knowledge"]
    assert resp.intent == "knowledge" and "흔한 실수" in resp.answer
    assert [c["doc_id"] for c in resp.contexts] == ["three-point-catch-and-shoot"]
    assert retriever.queries == ["캐치앤슛 연습할 때 자주 하는 실수가 뭐야?"]


def test_case31_unrelated_question_goes_to_knowledge_tool_and_is_declined(store):
    resp = answer_question(
        "오늘 서울 날씨 어때?",
        retriever=StubKnowledgeRetriever([]),
        store=store,
        parse_fn=lambda q: ParsedRequest(intent="other"),
        knowledge_llm=StubLLM("호출되면 안 된다"),
    )
    assert "drill_knowledge" in steps(resp)
    assert "찾을 수 없는" in resp.answer and resp.contexts == []


def test_knowledge_without_retriever_declines_instead_of_crashing(store):
    resp = ask("트래블링이 뭐야?", ParsedRequest(intent="knowledge"), store)
    assert "찾을 수 없는" in resp.answer


# --- 역사 -----------------------------------------------------------------------------

def test_case8_history_request_returns_story_with_sources(store):
    resp = ask("농구 역사에서 재미있는 이야기 하나 알려줘.", ParsedRequest(intent="history"), store)
    assert steps(resp) == ["parse_question", "basketball_history"]
    assert "출처:" in resp.answer and "https://" in resp.answer
    assert resp.contexts and resp.contexts[0]["text"] in resp.answer


def test_case11_exact_record_question_is_declined(store):
    resp = ask("1998년 KBL 정규리그에서 한 팀의 정확한 시즌 평균 득점이 몇 점이었어?", ParsedRequest(intent="history"), store)
    assert "확실하지 않아" in resp.answer
    history_step = next(t for t in resp.trace if t["step"] == "basketball_history")
    assert history_step["output"].startswith("거절")


# --- 기록과 난이도 판정 ------------------------------------------------------------------

def shot_report(drill, *sessions, past=()):
    return Report(drill=drill, shot_sessions=[SessionEntry(attempts=a, makes=m) for a, m in sessions], past_weeks=list(past))


def test_case2_sessions_are_summed_then_judged_keep(store):
    parsed = ParsedRequest(intent="record", reports=[shot_report("3점슛", (50, 10), (50, 30))])
    resp = ask("월요일에 3점슛 50회 중 10회...", parsed, store)
    assert steps(resp) == ["parse_question", "save_record", "judge_difficulty"]
    assert "난이도 유지" in resp.answer and "40.0%" in resp.answer
    assert "generate_plan" not in steps(resp)  # 난이도만 물었으면 계획은 만들지 않는다
    assert store.shots("default", "3점 캐치앤슛", "2026-W46") == [(50, 10), (50, 30)]


def test_case15_exactly_60_percent_raises(store):
    resp = ask("자유투 100회 중 60회", ParsedRequest(intent="record", reports=[shot_report("자유투", (100, 60))]), store)
    assert "제자리 자유투: 난이도 상향" in resp.answer


def test_case16_invalid_record_is_not_saved_and_not_judged(store):
    resp = ask("3점슛 20회 중 25회", ParsedRequest(intent="record", reports=[shot_report("3점슛", (20, 25))]), store)
    assert steps(resp) == ["parse_question", "save_record"]
    assert "저장 실패" in resp.trace[1]["output"] and "많을 수 없습니다" in resp.answer
    assert not store.has_records("default")


def test_case22_under_20_attempts_is_saved_but_keeps_difficulty(store):
    resp = ask("3점슛 15회 중 3회", ParsedRequest(intent="record", reports=[shot_report("3점슛", (15, 3))]), store)
    assert "난이도 유지" in resp.answer and "20회 미만" in resp.answer


def test_case23_past_rate_from_text_corrects_the_boundary(store):
    report = shot_report("3점슛", (200, 79), past=[PastWeek(rate_percent=45)])
    resp = ask("3주 전에 45%였고 이번 주 200회 중 79회", ParsedRequest(intent="record", reports=[report]), store)
    assert "난이도 유지" in resp.answer and "40%로 보정" in resp.answer
    assert "100회로 가정" in resp.answer  # 시도 횟수를 가정했다고 알려 준다


def test_case24_same_numbers_without_history_lower(store):
    resp = ask("처음 기록하는 건데 200회 중 79회", ParsedRequest(intent="record", reports=[shot_report("3점슛", (200, 79))]), store)
    assert "난이도 하향" in resp.answer


def test_case5_ratings_for_non_shot_drill(store):
    report = Report(drill="왼손 드리블", ratings=["쉬웠음", "쉬웠음", "적당"])
    resp = ask("왼손 드리블 쉬웠음 2번 적당 1번", ParsedRequest(intent="record", reports=[report]), store, retriever=None)
    assert "난이도 상향" in resp.answer or "찾지 못했어요" in resp.answer  # 연습 메뉴를 찾으면 상향
    resp = answer_question(
        "왼손 콘 지그재그 드리블 쉬웠음 2번 적당 1번",
        store=store, catalog=CATALOG, today=TODAY,
        parse_fn=lambda q: ParsedRequest(intent="record", reports=[Report(drill="왼손 콘 지그재그 드리블", ratings=["쉬웠음", "쉬웠음", "적당"])]),
    )
    assert "왼손 콘 지그재그 드리블: 난이도 상향" in resp.answer


def test_case14_three_way_tie_keeps(store):
    report = Report(drill="양손 크로스오버 드리블", ratings=["쉬웠음", "적당", "어려웠음"])
    resp = ask("평가 하나씩", ParsedRequest(intent="record", reports=[report]), store)
    assert "난이도 유지" in resp.answer and "동수" in resp.answer


def test_records_accumulate_across_requests_in_the_same_week(store):
    ask("월요일", ParsedRequest(intent="record", reports=[shot_report("3점슛", (50, 10))]), store)
    resp = ask("목요일", ParsedRequest(intent="record", reports=[shot_report("3점슛", (50, 30))]), store)
    assert "40.0%" in resp.answer and "난이도 유지" in resp.answer


def test_records_are_separate_per_user(store):
    answer_question("a", store=store, catalog=CATALOG, today=TODAY, user_id="a", parse_fn=lambda q: ParsedRequest(intent="record", reports=[shot_report("3점슛", (50, 10))]))
    resp = answer_question("b", store=store, catalog=CATALOG, today=TODAY, user_id="b", parse_fn=lambda q: ParsedRequest(intent="record", reports=[shot_report("3점슛", (50, 30))]))
    assert "60.0%" in resp.answer  # b의 기록만 센다 (a의 기록이 섞이면 40%)


# --- 기록 + 다음 주 계획 -----------------------------------------------------------------

def test_case3_record_then_plan_applies_the_lowering(store):
    parsed = ParsedRequest(intent="record", wants_next_plan=True, reports=[shot_report("3점슛", (50, 10))])
    resp = ask("이번 주 3점슛 50회 중 10회. 다음 주 계획 어떻게 바뀌어?", parsed, store,
               generate_fn=plan_of("미드레인지 제자리 점프슛", "제자리 자유투"))
    assert steps(resp) == ["parse_question", "save_record", "judge_difficulty", "validate_input", "search_drills", "generate_plan", "validate_plan"]
    assert "난이도 하향" in resp.answer and "미드레인지 제자리 점프슛" in resp.answer
    assert "3점 캐치앤슛" in resp.trace[2]["input"]


def test_case3_plan_that_ignores_the_lowering_is_regenerated(store):
    parsed = ParsedRequest(intent="record", wants_next_plan=True, reports=[shot_report("3점슛", (50, 10))])
    calls = []

    def fake(user, catalog, violations, judgments=None, menus=None):
        calls.append(violations)
        names = ["3점 캐치앤슛"] if len(calls) == 1 else ["미드레인지 제자리 점프슛"]
        return WeeklyPlan.model_validate(
            {"days": [{"day": "월", "drills": [{"name": n, "sets": 3, "reps": 10, "minutes": 10, "purpose": "p"} for n in names]}]}
        )

    resp = ask("계획", parsed, store, generate_fn=fake)
    assert len(calls) == 2 and "미드레인지 제자리 점프슛" in resp.answer
    assert steps(resp).count("generate_plan") == 2 and steps(resp).count("validate_plan") == 2


def test_case10_no_record_menu_is_kept_and_put_back_in_the_plan(store):
    parsed = ParsedRequest(intent="record", wants_next_plan=True, reports=[Report(drill="레이업", no_record=True)])
    resp = ask("레이업은 기록을 못 했어. 다음 주는?", parsed, store, generate_fn=plan_of("양손 레이업", "제자리 볼 핸들링"))
    assert "judge_difficulty" in steps(resp) and "save_record" not in steps(resp)
    assert "다음 주에 다시 넣습니다" in resp.answer and "양손 레이업" in resp.answer
    assert resp.answer.count("다시 넣") == 1  # 같은 말을 두 번 하지 않는다


def test_record_plan_infers_level_and_equipment_from_the_judged_menu(store):
    parsed = ParsedRequest(intent="record", wants_next_plan=True, reports=[shot_report("3점슛", (60, 42))])
    resp = ask("계획", parsed, store, generate_fn=plan_of("컷 후 무빙슛"))
    assert "중급으로 가정" in resp.answer and "골대은(는) 있다고 가정" in resp.answer


# --- 계획 ----------------------------------------------------------------------------

def test_case1_plan_uses_given_values_and_calls_tools_in_order(store):
    parsed = ParsedRequest(intent="plan", position="가드", level="중급", goals=["3점슛"], days_per_week=3,
                           minutes_per_session=40, equipment=["골대", "콘"])
    resp = ask("나는 가드이고 중급이야...", parsed, store, generate_fn=plan_of("3점 캐치앤슛", "풀업 점퍼", minutes=20))
    assert steps(resp) == ["parse_question", "validate_input", "search_drills", "generate_plan", "validate_plan"]
    assert resp.intent == "plan" and "농구 연습 계획 (주 3일 · 회당 40분)" in resp.answer
    assert "가정했어요" not in resp.answer  # 다 말했으면 가정 안내가 없다


def test_case9_missing_values_are_assumed_and_disclosed(store):
    parsed = ParsedRequest(intent="plan", goals=["3점슛"], equipment=[])
    resp = ask("나는 골대가 없어. 3점슛 연습 계획 짜줘.", parsed, store, generate_fn=plan_of("제자리 볼 핸들링"))
    assert "초급으로 가정" in resp.answer and "주 연습일을 말씀하지 않아 3일" in resp.answer
    assert "회당 연습 시간을 말씀하지 않아 40분" in resp.answer
    assert "골대가 있어야 해서 이번 계획에는 넣지 못했습니다" in resp.answer  # 장비 때문에 빠진 목표 안내


def test_unstated_equipment_means_ball_only_with_notice(store):
    resp = ask("계획", ParsedRequest(intent="plan", level="중급"), store, generate_fn=plan_of("제자리 볼 핸들링"))
    assert "공만 있는 것으로 가정" in resp.answer


def test_case17_invalid_days_is_rejected_before_any_planning(store):
    parsed = ParsedRequest(intent="plan", level="중급", days_per_week=8, minutes_per_session=40, equipment=[])
    resp = ask("주 8일 하루 40분", parsed, store)
    assert "주 연습일은 1~7 사이의 정수여야 합니다." in resp.answer
    assert "generate_plan" not in steps(resp)
    validate = next(t for t in resp.trace if t["step"] == "validate_input")
    assert "1~7 사이의 정수" in validate["output"]  # 입력 검증 단계에 거절 이유가 남는다


def test_case26_beginner_plan_uses_beginner_level_and_undecided_position(store):
    parsed = ParsedRequest(intent="plan", is_beginner=True, days_per_week=3, minutes_per_session=30, equipment=["골대", "콘"])
    resp = ask("농구를 이제 막 시작했어", parsed, store, generate_fn=plan_of("제자리 볼 핸들링", "제자리 자유투", minutes=15))
    assert "포지션: 미정 | 수준: 초급" in resp.answer and "초급으로 가정" not in resp.answer


def test_case28_stated_level_is_used_without_assumption(store):
    parsed = ParsedRequest(intent="plan", position="가드", level="중급", days_per_week=3, minutes_per_session=40, equipment=["골대"])
    resp = ask("지난주 기록이 있는 중급 가드야", parsed, store, generate_fn=plan_of("풀업 점퍼", minutes=20))
    assert "수준: 중급" in resp.answer and "실력 수준을 말씀하지" not in resp.answer


def test_contexts_of_a_plan_are_the_retrieved_menu_documents(store, retriever):
    parsed = ParsedRequest(intent="plan", position="가드", level="중급", days_per_week=3, minutes_per_session=40, equipment=["골대", "콘"])
    resp = ask("계획", parsed, store, retriever=retriever, generate_fn=plan_of("3점 캐치앤슛", "풀업 점퍼", minutes=20))
    assert resp.contexts and all(c.keys() == {"doc_id", "text"} for c in resp.contexts)
    assert "search_drills" in steps(resp)


# --- 연습 이름 연결 ---------------------------------------------------------------------

def test_map_drill_resolves_everyday_words():
    assert map_drill("3점슛", True, CATALOG).name == "3점 캐치앤슛"
    assert map_drill("자유투", True, CATALOG).name == "제자리 자유투"
    assert map_drill("레이업", False, CATALOG).name == "양손 레이업"
    assert map_drill("3점 캐치앤슛", True, CATALOG).name == "3점 캐치앤슛"
    assert map_drill("마라톤", True, CATALOG) is None


def test_map_drill_never_mixes_shooting_and_non_shooting(retriever):
    assert map_drill("드리블", False, CATALOG, retriever).is_shooting is False
    assert map_drill("3점슛", True, CATALOG, retriever).is_shooting is True


# --- 난이도만 물은 질문에는 계획을 만들지 않는다 ---------------------------------------------

def test_case24_difficulty_only_question_does_not_make_a_plan_even_if_the_model_asks_for_one(store):
    parsed = ParsedRequest(intent="record", wants_next_plan=True, reports=[shot_report("3점슛", (200, 79))])
    resp = ask("처음 기록하는 건데 3점슛 200회 중 79회 넣었어. 다음 주 난이도는?", parsed, store)
    assert "generate_plan" not in steps(resp) and "난이도 하향" in resp.answer


@pytest.mark.parametrize(
    "question",
    [
        "이번 주 3점슛 50회 중 10회 성공했어. 다음 주 계획 어떻게 바뀌어?",
        "이번 주 3점슛 60회 중 42회 성공했어. 다음 주는 어떻게 해야 해?",
        "지난주 계획에 있던 레이업 연습 메뉴는 한 번도 기록을 못 했어. 다음 주는 어떻게 돼?",
    ],
)
def test_plan_words_keep_the_plan_when_the_user_asked_for_it(store, question):
    parsed = ParsedRequest(intent="record", wants_next_plan=True, reports=[shot_report("3점슛", (50, 10))])
    resp = ask(question, parsed, store, generate_fn=plan_of("미드레인지 제자리 점프슛", "양손 레이업"))
    assert "generate_plan" in steps(resp)


def test_model_saying_no_plan_is_respected_even_with_plan_words(store):
    parsed = ParsedRequest(intent="record", wants_next_plan=False, reports=[shot_report("3점슛", (50, 10))])
    resp = ask("3점슛 50회 중 10회 넣었어. 계획은 아직 필요 없어", parsed, store)
    assert "generate_plan" not in steps(resp)
