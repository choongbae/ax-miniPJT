"""농구 지식 도구 (T18).

준비된 문서(data/menus, data/guides)만 근거로 한다. 근거가 없으면 지어내지 않고 안내 문구를 돌려준다.
- 카드용 요약: 연습 메뉴 문서에서 자세 팁 1개와 흔한 실수 1개를 코드로 뽑는다. (LLM을 쓰지 않으므로 다른 메뉴 내용이 섞이지 않는다.)
- 질문 답변: 질문과 가까운 문서를 하이브리드로 찾고, 그 문서만 근거로 LLM이 2~4문장으로 답한다.
"""
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_llm_with_fallbacks
from src.retriever import MenuDoc
from src.tracing import traced

MAX_DISTANCE = 0.7  # 이보다 먼 문서는 근거로 쓰지 않는다 (농구 질문은 0.61 이하, 무관한 질문은 0.82 이상이었다)
MARGIN = 0.12  # 가장 가까운 문서보다 이만큼 넘게 먼 문서는 섞이지 않게 뺀다
NOT_FOUND_ANSWER = (
    "준비된 농구 자료에서는 찾을 수 없는 내용이라 정확히 답하기 어려워요. "
    "연습 메뉴, 기본기, 용어, 기본 규칙, 준비운동 같은 내용을 물어봐 주세요."
)
NOT_FOUND_TOKEN = "NOT_FOUND"

SYSTEM = f"""당신은 농구 연습을 돕는 안내자입니다. 아래 '자료'에 적힌 내용만 근거로 질문에 한국어 존댓말로 답합니다.

1. 답은 2~4문장으로 짧게 씁니다.
2. 자료에 없는 내용은 덧붙이지 않습니다. 선수 기록, 경기 결과, 연도 같은 사실은 자료에 없으면 만들지 않습니다.
   자료에 쓰여 있지 않은 이유, 목적, 효과, 규칙이 생긴 배경도 덧붙이지 않고, 마무리 격려 문장도 쓰지 않습니다.
3. 질문과 관련 없는 자료는 쓰지 않습니다. 질문이 묻는 연습 메뉴와 다른 메뉴의 내용을 섞지 않습니다.
4. 자료로 답할 수 없으면 {NOT_FOUND_TOKEN} 한 단어만 출력합니다.
5. 의료 진단이나 치료 조언은 하지 않습니다."""

HUMAN = """[자료]
{docs}

[질문]
{question}"""


@dataclass(frozen=True)
class KnowledgeAnswer:
    answer: str
    contexts: list[dict]  # 답의 근거로 쓴 문서 [{"doc_id", "text"}]
    grounded: bool  # 근거 문서로 답했으면 True


def _bullets(text: str, title: str) -> list[str]:
    """'## 제목' 섹션의 '- ' 항목들."""
    match = re.search(rf"## {title}\n(.*?)(?=\n## |\Z)", text, re.S)
    if not match:
        return []
    return [line[2:].strip() for line in match.group(1).splitlines() if line.startswith("- ")]


def menu_card_knowledge(doc: MenuDoc) -> list[str]:
    """연습 메뉴 카드에 보여 줄 2줄 요약: 핵심 자세 팁 1개, 자주 하는 실수 1개. 해당 메뉴 문서에서만 뽑는다."""
    lines: list[str] = []
    tips = _bullets(doc.text, "자세 팁")
    mistakes = _bullets(doc.text, "흔한 실수")
    if tips:
        lines.append(f"자세 팁: {tips[0]}")
    if mistakes:
        lines.append(f"자주 하는 실수: {mistakes[0]}")
    return lines


def cards_by_name(docs: list[MenuDoc]) -> dict[str, list[str]]:
    """연습 메뉴 이름 -> 카드 요약. 안내 문서는 제외한다."""
    return {d.name: menu_card_knowledge(d) for d in docs if d.kind == "menu"}


def _format_docs(contexts: list[dict], names: dict[str, str]) -> str:
    return "\n\n".join(f"### {names.get(c['doc_id'], c['doc_id'])}\n{c['text']}" for c in contexts)


def _content_text(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content)


@traced("drill_knowledge", "chain", keep=("question", "k"))
def answer_knowledge(question: str, retriever, llm=None, k: int = 3) -> KnowledgeAnswer:
    """질문에 준비된 문서만 근거로 답한다. 근거가 없으면 grounded=False와 안내 문구를 돌려준다."""
    results = retriever.search_hybrid(question, k=k, max_distance=MAX_DISTANCE, margin=MARGIN)
    if not results:
        return KnowledgeAnswer(NOT_FOUND_ANSWER, [], False)

    contexts = [{"doc_id": r.doc.doc_id, "text": r.doc.text} for r in results]
    names = {r.doc.doc_id: r.doc.name for r in results}
    llm = llm or get_llm_with_fallbacks()
    response = llm.invoke(
        [
            SystemMessage(content=SYSTEM),
            HumanMessage(content=HUMAN.format(docs=_format_docs(contexts, names), question=question)),
        ]
    )
    text = _content_text(response).strip()
    if not text or NOT_FOUND_TOKEN in text:
        return KnowledgeAnswer(NOT_FOUND_ANSWER, [], False)
    return KnowledgeAnswer(add_safety_notes(text, contexts), contexts, True)


def safety_notes(contexts: list[dict]) -> list[str]:
    """근거 문서에 적힌 통증·전문가 상담 안내 문장. 의료 조언을 하지 않는 서비스라 문서에 있으면 답에 반드시 들어가야 한다."""
    notes = []
    for c in contexts:
        for line in c["text"].splitlines():
            line = line.strip().lstrip("- ").strip()
            if "통증" in line and "전문가" in line and line not in notes:
                notes.append(line)
    return notes


def add_safety_notes(answer: str, contexts: list[dict]) -> str:
    """모델이 안전 안내를 빠뜨렸으면 문서의 문장을 그대로 덧붙인다 (모델이 이미 말했으면 중복하지 않는다)."""
    if "전문가" in answer:
        return answer
    notes = safety_notes(contexts)
    return answer + "\n\n※ " + " ".join(notes) if notes else answer
