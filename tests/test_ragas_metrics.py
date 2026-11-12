"""RAGAS 지표 계산 테스트 (직접 구현). 모델과 임베딩은 가짜로 바꾸고 점수 계산만 확인한다."""
import pytest

from evaluation.ragas_metrics import METRICS, RagasScorer, average, cosine, precision_at_k, ratio, split_reference

CTX = [{"doc_id": "a", "text": "A 문서"}, {"doc_id": "b", "text": "B 문서"}, {"doc_id": "c", "text": "C 문서"}]


def scorer(**over):
    base = dict(
        extract_claims=lambda answer: ["주장1", "주장2", "주장3", "주장4"],
        check_support=lambda statements, docs: [True, True, False, True][: len(statements)] if len(statements) <= 4 else [True] * len(statements),
        check_relevance=lambda q, ctx: [True, False, True][: len(ctx)],
        generate_questions=lambda answer: (["q1", "q2"], False),
        embed=lambda texts: [[1.0, 0.0]] + [[1.0, 0.0], [0.0, 1.0]][: len(texts) - 1],
    )
    return RagasScorer(**{**base, **over})


def test_ratio_and_cosine():
    assert ratio([True, True, False]) == 0.667 and ratio([]) is None
    assert cosine([1, 0], [1, 0]) == 1.0 and cosine([1, 0], [0, 1]) == 0.0 and cosine([0, 0], [1, 0]) == 0.0


@pytest.mark.parametrize("relevant,expected", [
    ([True, True, True], 1.0),
    ([True, False, True], 0.833),  # (1/1 + 2/3) / 2
    ([False, False, True], 0.333),  # 관련 문서가 뒤쪽에 있으면 낮다
    ([False, False], 0.0),
    ([], None),
])
def test_context_precision_rewards_relevant_documents_ranked_first(relevant, expected):
    assert precision_at_k(relevant) == expected


def test_all_four_metrics_are_computed():
    s = scorer().score("질문", "답변", CTX, ["기준1", "기준2", "기준3"])
    assert set(s) == set(METRICS)
    assert s["faithfulness"] == 0.75  # 4주장 중 3개 뒷받침
    assert s["context_recall"] == 0.667  # 기준 3문장 중 2개 (가짜 판정 True, True, False)
    assert s["context_precision"] == 0.833
    assert s["answer_relevancy"] == 0.5  # 유사도 1.0과 0.0의 평균


def test_no_contexts_means_not_applicable():
    for contexts in ([], None):
        assert scorer().score("질문", "답변", contexts or [], ["기준"]) == {m: None for m in METRICS}
    assert scorer().score("질문", "   ", CTX, ["기준"]) == {m: None for m in METRICS}


def test_noncommittal_answer_has_zero_relevancy():
    s = scorer(generate_questions=lambda a: ([], True)).score("질문", "찾을 수 없어요", CTX, ["기준"])
    assert s["answer_relevancy"] == 0.0


def test_missing_reference_or_claims_skip_only_those_metrics():
    s = scorer(extract_claims=lambda a: []).score("질문", "답변", CTX, [])
    assert s["faithfulness"] is None and s["context_recall"] is None and s["context_precision"] == 0.833


def test_average_skips_not_applicable():
    rows = [{"faithfulness": 1.0, "context_recall": None, "context_precision": 0.5, "answer_relevancy": 0.2},
            None, {"faithfulness": 0.5, "context_recall": None, "context_precision": None, "answer_relevancy": 0.4}]
    a = average(rows)
    assert a["faithfulness"] == {"mean": 0.75, "n": 2} and a["context_recall"] == {"mean": None, "n": 0}
    assert a["context_precision"] == {"mean": 0.5, "n": 1} and a["answer_relevancy"]["mean"] == pytest.approx(0.3)


def test_reference_comes_from_expected_traits():
    assert split_reference("a; b ;;c") == ["a", "b", "c"] and split_reference("") == []


def test_format_traits_are_not_part_of_the_reference():
    traits = "림이나 백보드에 맞아도 속도가 줄어든다는 이유; 준비된 문서 근거; 2~4문장; 정중한 존댓말; 3줄 이내"
    assert split_reference(traits) == ["림이나 백보드에 맞아도 속도가 줄어든다는 이유"]
