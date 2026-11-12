"""평가 러너의 코드 판정 부분 테스트 (T29). 모델은 부르지 않는다."""
import pytest

from evaluation.run_eval import (
    case_passed, contract_problems, load_cases, missing_tools, render_markdown, run_case, split_items, summarize,
)

GOOD = {"answer": "a", "contexts": [{"doc_id": "d", "text": "t"}], "trace": [{"step": "s", "input": "i", "output": "o"}]}


def test_all_cases_load_and_have_the_columns():
    cases = load_cases()
    assert len(cases) == 32 and {c["category"] for c in cases} == {"positive", "edge", "negative", "guardrail"}
    assert all(c["id"] and c["input"] and c["expected_traits"] for c in cases)
    assert [c["id"] for c in load_cases(ids={"2", "18"})] == ["2", "18"]


def test_expected_tools_name_real_trace_steps():
    known = {"search_drills", "generate_plan", "validate_plan", "save_record", "judge_difficulty", "retrieve", "drill_knowledge",
             "basketball_history", "validate_input", "guardrail", "output_check", "parse_question"}
    used = {t for c in load_cases() for t in split_items(c["expected_tools"])}
    assert used <= known, used - known


def test_contract_accepts_the_standard_shape_and_empty_lists():
    assert contract_problems(GOOD) == []
    assert contract_problems({"answer": "a", "contexts": [], "trace": []}) == []


@pytest.mark.parametrize("bad", [
    [], {"answer": "a", "contexts": [], "trace": [], "intent": "x"}, {"answer": "a", "contexts": []},
    {**GOOD, "answer": 1}, {**GOOD, "contexts": [{"doc_id": "d"}]}, {**GOOD, "contexts": [{"doc_id": "d", "text": 1}]},
    {**GOOD, "trace": [{"step": "s", "input": "i"}]}, {**GOOD, "trace": "x"},
])
def test_contract_rejects_deviations(bad):
    assert contract_problems(bad)


def test_tools_must_appear_in_order_but_other_steps_may_come_between():
    steps = ["parse_question", "search_drills", "generate_plan", "validate_plan", "output_check"]
    assert missing_tools(["search_drills", "generate_plan", "validate_plan"], steps) == []
    assert missing_tools(["generate_plan", "search_drills"], steps) == ["search_drills"]  # 순서가 뒤집히면 빠진 것으로 본다
    assert missing_tools(["save_record"], steps) == ["save_record"]
    assert missing_tools([], steps) == []


def result(**kw):
    base = {"error": "", "contract_problems": [], "missing_tools": [], "judge": None, "category": "positive", "seconds": 1.0}
    return {**base, **kw}


def test_pass_needs_contract_tools_and_judge_when_judged():
    assert case_passed(result())
    assert not case_passed(result(error="boom"))
    assert not case_passed(result(contract_problems=["x"]))
    assert not case_passed(result(missing_tools=["save_record"]))
    assert case_passed(result(judge={"traits_unmet": [], "forbidden_hit": []}))
    assert not case_passed(result(judge={"traits_unmet": ["a"], "forbidden_hit": []}))
    assert not case_passed(result(judge={"traits_unmet": [], "forbidden_hit": ["b"]}))


def test_summary_and_markdown():
    rs = [{**result(), "id": "1", "input": "q|1", "steps": ["a"], "passed": True},
          {**result(category="edge", missing_tools=["x"]), "id": "2", "input": "q2", "steps": [], "passed": False}]
    s = summarize(rs)
    assert s["total"] == {"passed": 1, "count": 2} and s["by_category"]["edge"] == {"passed": 0, "count": 1}
    md = render_markdown(rs, "제목")
    assert "통과 1/2" in md and "**실패**" in md and "빠진 도구 x" in md and "q/1" in md  # 표를 깨는 | 는 바꾼다


def test_run_case_goes_through_the_api_with_a_fresh_store_and_never_raises(monkeypatch):
    import evaluation.run_eval as ev
    import src.api as api

    seen = []

    def fake_answer(question, retriever=None, store=None, user_id="default"):
        from src.orchestrator import QueryResponse

        seen.append(id(store))
        return QueryResponse("답", [], [{"step": "guardrail", "input": "i", "output": "o"}], "blocked")

    real = api.create_app
    monkeypatch.setattr(api, "create_app", lambda **kw: real(**{**kw, "answer_fn": fake_answer}))
    case = {"id": "x", "category": "guardrail", "input": "q", "expected_tools": "guardrail", "expected_traits": "t", "forbidden": ""}
    a, b = run_case(case, None), run_case(case, None)
    assert a["passed"] and a["steps"] == ["guardrail"] and a["answer"] == "답"
    assert seen[0] != seen[1]  # 케이스마다 새 저장소

    monkeypatch.setattr(api, "create_app", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    err = run_case(case, None)
    assert not err["passed"] and "RuntimeError" in err["error"]


def test_run_errors_are_counted_apart_from_failures():
    from evaluation.run_eval import is_error

    ok = {**result(), "id": "1", "input": "q", "steps": [], "passed": True}
    wrong = {**result(missing_tools=["x"]), "id": "2", "input": "q", "steps": [], "passed": False}
    err = {**result(error="HTTP 500"), "id": "3", "input": "q", "steps": [], "passed": False}
    assert [is_error(r) for r in (ok, wrong, err)] == [False, False, True]
    assert summarize([ok, wrong, err])["errors"] == 1
    md = render_markdown([ok, wrong, err], "t")
    assert "실행 오류 1건" in md and "| 오류 |" in md and "**실패**" in md


def test_plan_menu_names_are_extracted_from_a_plan_answer():
    from evaluation.run_eval import plan_menu_names

    answer = """농구 연습 계획
[월] 총 40분
  1. 제자리 볼 핸들링 - 3세트 × 20회 (10분)
     목적: x
  2. 풀업 점퍼 - 4세트 × 10회 (20분)
[수] 총 40분
  1. 풀업 점퍼 - 4세트 × 10회 (20분)"""
    assert plan_menu_names(answer) == ["제자리 볼 핸들링", "풀업 점퍼"]  # 중복 없이 처음 나온 순서
    assert plan_menu_names("3점 캐치앤슛: 난이도 유지.") == []
