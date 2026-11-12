from types import SimpleNamespace

from src.agent import format_result, run_agent
from src.knowledge import (
    NOT_FOUND_ANSWER,
    answer_knowledge,
    cards_by_name,
    menu_card_knowledge,
)
from src.models import UserInput, WeeklyPlan
from src.retriever import SearchResult, load_all_docs, load_menu_docs
from src.tools import load_drills

MENU_DOCS = load_menu_docs()
BY_ID = {d.doc_id: d for d in load_all_docs()}
CATALOG = load_drills()


# --- 카드용 요약 -----------------------------------------------------------------

def test_card_has_two_lines_from_the_menu_own_document():
    doc = BY_ID["three-point-catch-and-shoot"]
    lines = menu_card_knowledge(doc)
    assert len(lines) == 2
    assert lines[0].startswith("자세 팁: ") and lines[1].startswith("자주 하는 실수: ")
    for line in lines:
        assert line.split(": ", 1)[1] in doc.text  # 그 메뉴 문서에 있는 문장 그대로


def test_every_menu_has_a_card_and_cards_never_use_other_menus_text():
    cards = cards_by_name(MENU_DOCS)
    assert len(cards) == 29 and all(len(v) == 2 for v in cards.values())
    for doc in MENU_DOCS:
        for line in cards[doc.name]:
            assert line.split(": ", 1)[1] in doc.text


def test_cards_exclude_guide_documents():
    names = set(cards_by_name(load_all_docs()))
    assert "슛 용어 설명" not in names and "3점 캐치앤슛" in names


def test_card_is_shown_under_each_menu_in_the_final_answer():
    plan = WeeklyPlan.model_validate(
        {"days": [{"day": "월", "drills": [{"name": "3점 캐치앤슛", "sets": 4, "reps": 10, "minutes": 20, "purpose": "타이밍"}]}]}
    )
    user = UserInput(position="가드", level="중급", goals=[], days_per_week=3, minutes_per_session=40, equipment=["골대"])
    cards = cards_by_name(MENU_DOCS)
    text = format_result({"user": user, "plan": plan, "status": "ok", "violations": [], "cards": cards})
    assert "     자세 팁: " in text and "     자주 하는 실수: " in text


def test_agent_result_carries_cards_for_planned_menus_only():
    plan = WeeklyPlan.model_validate(
        {"days": [{"day": "월", "drills": [{"name": "제자리 볼 핸들링", "sets": 3, "reps": 10, "minutes": 30, "purpose": "p"}]}]}
    )
    user = UserInput(position="가드", level="초급", goals=[], days_per_week=3, minutes_per_session=40, equipment=[])
    state = run_agent(user, CATALOG, generate_fn=lambda *a, **k: plan)
    assert list(state["cards"]) == ["제자리 볼 핸들링"]


# --- 질문 답변 -------------------------------------------------------------------

class StubRetriever:
    def __init__(self, results):
        self.results, self.calls = results, []

    def search_hybrid(self, query, k=3, max_distance=None, margin=None, kinds=None):
        self.calls.append((query, k, max_distance, margin))
        return self.results


class StubLLM:
    def __init__(self, text):
        self.text, self.messages = text, None

    def invoke(self, messages):
        self.messages = messages
        return SimpleNamespace(content=self.text)


def results_for(*doc_ids):
    return [SearchResult(BY_ID[d], 0.5) for d in doc_ids]


def test_grounded_answer_uses_only_retrieved_documents():
    retriever = StubRetriever(results_for("three-point-catch-and-shoot"))
    llm = StubLLM("공을 받은 뒤 한 번 내려놓았다가 쏘는 것이 가장 흔한 실수입니다.")
    out = answer_knowledge("캐치앤슛 연습할 때 자주 하는 실수가 뭐야?", retriever, llm=llm)  # 케이스 7
    assert out.grounded and "흔한 실수" in out.answer
    assert [c["doc_id"] for c in out.contexts] == ["three-point-catch-and-shoot"]
    prompt_text = "\n".join(m.content for m in llm.messages)
    assert "3점 캐치앤슛" in prompt_text and "피벗 연습" not in prompt_text  # 다른 메뉴 내용은 들어가지 않는다


def test_no_documents_means_not_found_without_calling_the_llm():
    llm = StubLLM("호출되면 안 된다")
    out = answer_knowledge("오늘 서울 날씨 어때?", StubRetriever([]), llm=llm)
    assert out.grounded is False and out.answer == NOT_FOUND_ANSWER and out.contexts == []
    assert llm.messages is None


def test_llm_saying_not_found_gives_the_standard_message_and_no_contexts():
    out = answer_knowledge("1998년 KBL 평균 득점은?", StubRetriever(results_for("rules-basics")), llm=StubLLM("NOT_FOUND"))
    assert out.grounded is False and out.answer == NOT_FOUND_ANSWER and out.contexts == []


def test_search_is_called_with_distance_limit_and_margin():
    retriever = StubRetriever(results_for("rules-basics"))
    answer_knowledge("트래블링이 뭐야?", retriever, llm=StubLLM("규칙 설명입니다."))
    query, k, max_distance, margin = retriever.calls[0]
    assert max_distance == 0.7 and margin == 0.12 and k == 3


def test_system_prompt_forbids_making_things_up_and_medical_advice():
    llm = StubLLM("답")
    answer_knowledge("워밍업은?", StubRetriever(results_for("warmup-cooldown")), llm=llm)
    system = llm.messages[0].content
    assert "자료에 없는 내용은 덧붙이지 않습니다" in system and "의료" in system and "NOT_FOUND" in system


def test_list_content_from_llm_is_joined():
    class ListLLM:
        def invoke(self, messages):
            return SimpleNamespace(content=[{"type": "text", "text": "첫째. "}, {"type": "text", "text": "둘째."}])

    out = answer_knowledge("자유투?", StubRetriever(results_for("free-throw-set")), llm=ListLLM())
    assert out.answer == "첫째. 둘째."


# --- 안전 안내 (T31): 근거 문서에 통증·전문가 상담 안내가 있으면 답에 반드시 들어간다 ---------------------

def test_safety_note_is_added_from_the_document_when_the_model_omits_it():
    from src.knowledge import add_safety_notes, safety_notes

    ctx = [{"doc_id": "warmup", "text": "## 주의\n- 연습 중 통증이 계속되면 쉬세요. 통증이 이어지면 전문가와 상담하세요.\n- 다른 줄"}]
    assert safety_notes(ctx) == ["연습 중 통증이 계속되면 쉬세요. 통증이 이어지면 전문가와 상담하세요."]
    out = add_safety_notes("가볍게 걷습니다.", ctx)
    assert out.startswith("가볍게 걷습니다.") and out.endswith("전문가와 상담하세요.") and "※" in out


def test_safety_note_is_not_duplicated_or_invented():
    from src.knowledge import add_safety_notes

    ctx = [{"doc_id": "d", "text": "- 연습 중 통증이 계속되면 쉬세요. 전문가와 상담하세요."}]
    already = "가볍게 걷습니다. 통증이 있으면 전문가와 상담하세요."
    assert add_safety_notes(already, ctx) == already  # 모델이 이미 말했으면 그대로
    assert add_safety_notes("답", [{"doc_id": "d", "text": "- 통증 이야기 없음"}]) == "답"  # 문서에 없으면 만들지 않는다
