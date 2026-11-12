"""RAGAS 네 지표를 RAGAS의 정의대로 직접 계산한다 (ragas 라이브러리는 쓰지 않는다).

판정이 필요한 부분(주장 쪼개기, 문서가 주장을 뒷받침하는지, 문서가 질문에 관련 있는지, 답변에서 질문 만들기)만 모델이 하고,
점수 계산은 모두 코드가 한다. 질문 유사도는 서비스 검색과 같은 Titan 임베딩을 쓴다.

- faithfulness      = 답변의 주장 중 검색된 문서가 뒷받침하는 비율
- answer_relevancy  = 답변에서 거꾸로 만든 질문들과 실제 질문의 임베딩 코사인 유사도 평균 (답변이 얼버무림이면 0)
- context_precision = 검색된 문서를 순서대로 봤을 때 관련 문서가 앞쪽에 몰려 있는 정도 (순위 가중 평균 정밀도)
- context_recall    = 기준 답변(reference)의 문장 중 검색된 문서가 뒷받침하는 비율

기준 답변은 평가 세트에 따로 없어서 각 케이스의 expected_traits(기대 항목)를 문장으로 보고 쓰되, 말투·분량·출처 같은 형식 항목은 뺀다(문서로 뒷받침할 수 없다).
검색된 문서가 없는 케이스(가드레일 거절, 기록 입력 등)는 검색 품질을 잴 수 없으므로 네 지표 모두 None(해당 없음)이다.
"""
import math
import re
from dataclasses import dataclass
from typing import Callable

from pydantic import BaseModel, Field

METRICS = ("context_recall", "context_precision", "faithfulness", "answer_relevancy")
N_QUESTIONS = 3  # answer_relevancy에서 답변마다 만드는 질문 수


# --- 모델이 채우는 구조 ---------------------------------------------------------------------

class Claims(BaseModel):
    claims: list[str] = Field(description="답변을 더는 쪼갤 수 없는 사실 주장 문장들로 나눈 목록")


class SupportItem(BaseModel):
    statement: str
    supported: bool = Field(description="주어진 문서만으로 이 문장이 뒷받침되면 true")


class Support(BaseModel):
    items: list[SupportItem]


class RelevanceItem(BaseModel):
    doc_id: str
    relevant: bool = Field(description="질문에 답하는 데 이 문서가 쓸모 있으면 true")


class Relevance(BaseModel):
    items: list[RelevanceItem]


class GeneratedQuestions(BaseModel):
    questions: list[str] = Field(description="이 답변이 대답하는 질문 후보")
    noncommittal: bool = Field(description="답변이 모른다·찾을 수 없다·거절처럼 얼버무림이면 true")


# --- 코드 계산 (모델 없음, 테스트 대상) --------------------------------------------------------

def ratio(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 3) if flags else None


def precision_at_k(relevant: list[bool]) -> float | None:
    """RAGAS context_precision: 관련 문서가 나온 순위마다의 정밀도(그 순위까지 중 관련 비율)를 평균한다. 관련 문서가 없으면 0."""
    if not relevant:
        return None
    hits, total = 0, 0.0
    for k, rel in enumerate(relevant, start=1):
        if rel:
            hits += 1
            total += hits / k
    return round(total / hits, 3) if hits else 0.0


def cosine(a: list[float], b: list[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


# 문서 내용이 아니라 말투·분량·출처 같은 형식을 요구하는 기대 항목은 문서로 뒷받침할 수 없으므로 기준 답변에서 뺀다.
FORMAT_TRAIT = re.compile(r"존댓말|문서 근거|\d+\s*[~\-]\s*\d+\s*(문장|줄)|문장 이내|줄 이내")


def split_reference(traits: str) -> list[str]:
    items = [t.strip() for t in (traits or "").split(";") if t.strip()]
    return [t for t in items if not FORMAT_TRAIT.search(t)]


# --- 계산기 ---------------------------------------------------------------------------------

@dataclass
class RagasScorer:
    """모델 호출을 함수로 받아서(테스트에서는 가짜) 네 지표를 계산한다."""
    extract_claims: Callable[[str], list[str]]  # 답변 -> 주장들
    check_support: Callable[[list[str], str], list[bool]]  # (문장들, 문서 묶음 글) -> 문장별 뒷받침 여부 (같은 길이)
    check_relevance: Callable[[str, list[dict]], list[bool]]  # (질문, 문서들) -> 문서별 관련 여부 (같은 길이)
    generate_questions: Callable[[str], tuple[list[str], bool]]  # 답변 -> (질문들, 얼버무림 여부)
    embed: Callable[[list[str]], list[list[float]]]

    def score(self, question: str, answer: str, contexts: list[dict], reference: list[str]) -> dict:
        if not contexts or not answer.strip():
            return {m: None for m in METRICS}
        docs = "\n\n".join(f"[{c['doc_id']}]\n{c['text']}" for c in contexts)
        out: dict = {}

        claims = self.extract_claims(answer)
        out["faithfulness"] = ratio(self.check_support(claims, docs)) if claims else None

        out["context_recall"] = ratio(self.check_support(reference, docs)) if reference else None

        out["context_precision"] = precision_at_k(self.check_relevance(question, contexts))

        questions, noncommittal = self.generate_questions(answer)
        if noncommittal:
            out["answer_relevancy"] = 0.0
        elif questions:
            vectors = self.embed([question] + questions)
            sims = [cosine(vectors[0], v) for v in vectors[1:]]
            out["answer_relevancy"] = round(sum(sims) / len(sims), 3)
        else:
            out["answer_relevancy"] = None
        return out


def average(rows: list[dict]) -> dict:
    """지표별 평균과 계산한 케이스 수. None(해당 없음)은 평균에서 뺀다."""
    res = {}
    for m in METRICS:
        vals = [r[m] for r in rows if r and r.get(m) is not None]
        res[m] = {"mean": round(sum(vals) / len(vals), 3) if vals else None, "n": len(vals)}
    return res


# --- 실제 모델 연결 ---------------------------------------------------------------------------

def make_scorer() -> RagasScorer:
    from langchain_core.prompts import ChatPromptTemplate

    from src.llm import structured_chain
    from src.retriever import get_embeddings

    def chain(system: str, human: str, schema):
        return structured_chain(ChatPromptTemplate.from_messages([("system", system), ("human", human)]), schema)

    claims_chain = chain(
        "답변을 더는 쪼갤 수 없는 사실 주장 문장들로 나눕니다. 인사말, 안내 문구, 출처 표시, '※'로 시작하는 가정 안내는 주장이 아니므로 뺍니다. 원문에 없는 내용은 만들지 않습니다.",
        "{answer}", Claims)
    support_chain = chain(
        "문장 목록의 각 문장이 아래 '문서'의 내용만으로 뒷받침되는지 판정합니다. 문서에 없는 사실이거나 문서와 다르면 false입니다. 입력한 문장 순서와 개수 그대로, 각 문장을 statement에 그대로 적어 답합니다.",
        "문서:\n{docs}\n\n문장 목록:\n{statements}", Support)
    relevance_chain = chain(
        "질문에 답하는 데 각 문서가 쓸모 있는지 판정합니다. 질문과 직접 관련 있는 내용이 있으면 true, 무관하면 false입니다. 문서마다 doc_id를 그대로 적어 답합니다.",
        "질문: {question}\n\n문서:\n{docs}", Relevance)
    questions_chain = chain(
        f"주어진 답변이 대답하는 질문을 {N_QUESTIONS}개 만듭니다. 답변이 '모른다', '찾을 수 없다', 거절·회피라면 noncommittal을 true로 합니다.",
        "{answer}", GeneratedQuestions)
    embeddings = get_embeddings()

    def extract_claims(answer: str) -> list[str]:
        return [c for c in claims_chain.invoke({"answer": answer}).claims if c.strip()]

    def check_support(statements: list[str], docs: str) -> list[bool]:
        res = support_chain.invoke({"docs": docs, "statements": "\n".join(f"- {s}" for s in statements)}).items
        by_text = {i.statement.strip(): i.supported for i in res}
        if all(s.strip() in by_text for s in statements):
            return [by_text[s.strip()] for s in statements]
        if len(res) == len(statements):  # 모델이 문장을 조금 바꿔 적었으면 순서로 맞춘다
            return [i.supported for i in res]
        raise ValueError(f"판정 개수가 문장 수와 다름: {len(res)} != {len(statements)}")

    def check_relevance(question: str, contexts: list[dict]) -> list[bool]:
        docs = "\n\n".join(f"[{c['doc_id']}]\n{c['text']}" for c in contexts)
        res = {i.doc_id: i.relevant for i in relevance_chain.invoke({"question": question, "docs": docs}).items}
        return [bool(res.get(c["doc_id"], False)) for c in contexts]

    def generate_questions(answer: str) -> tuple[list[str], bool]:
        r = questions_chain.invoke({"answer": answer})
        return [q for q in r.questions if q.strip()][:N_QUESTIONS], r.noncommittal

    return RagasScorer(extract_claims, check_support, check_relevance, generate_questions, embeddings.embed_documents)
