"""평가 러너 (T29): evaluation/test_queries.csv의 질의를 /query API로 보내 케이스별 통과·실패 표를 만든다.

    python -m evaluation.run_eval                      # 32건 전체, 도구 호출과 응답 규약만 확인 (코드 판정)
    python -m evaluation.run_eval --judge              # 기대 항목·금지 항목까지 모델로 판정해서 함께 본다
    python -m evaluation.run_eval --ids 2,3,18 --repeat 3
    python -m evaluation.run_eval --out evaluation/results/round1.json --report evaluation/results/round1.md

실제 Bedrock 모델을 부르므로 .env가 필요하다. 케이스마다 새 저장소(임시 DB)로 앱을 만들어서 이전 케이스의 기록이 섞이지 않는다.

판정 방식 (코드로 정할 수 있는 것은 코드로, 문장 이해가 필요한 것만 모델로):
- 응답 규약: 키가 answer·contexts·trace뿐이고 타입이 맞는다 (코드)
- 도구: expected_tools가 trace의 step에 순서대로 나타난다 (코드)
- 기대 항목·금지 항목: --judge를 켰을 때만, 모델이 답변 글을 보고 항목별로 충족·위반을 판정한다 (모델, 오차가 있을 수 있다)
통과 = 규약 통과 + 도구 통과 (+ --judge일 때 기대 항목 모두 충족 + 금지 항목 위반 없음)
"""
import argparse
import csv
import json
import re
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.ragas_metrics import average  # noqa: E402

CASES_PATH = ROOT / "evaluation" / "test_queries.csv"


# --- 코드 판정 (모델 호출 없음, 테스트 대상) -----------------------------------------------

def load_cases(path: Path = CASES_PATH, ids: set[str] | None = None) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if not ids or r["id"] in ids]


def split_items(text: str) -> list[str]:
    return [x.strip() for x in (text or "").split(";") if x.strip()]


def contract_problems(body) -> list[str]:
    """응답이 /query 규약과 같은지: 키 3개, answer는 문자열, contexts·trace는 정해진 모양의 목록."""
    if not isinstance(body, dict):
        return ["응답이 JSON 객체가 아님"]
    problems = []
    if set(body) != {"answer", "contexts", "trace"}:
        problems.append(f"키가 규약과 다름: {sorted(body)}")
        return problems
    if not isinstance(body["answer"], str):
        problems.append("answer가 문자열이 아님")
    ctx, trace = body["contexts"], body["trace"]
    if not isinstance(ctx, list) or not all(isinstance(c, dict) and set(c) == {"doc_id", "text"} and all(isinstance(v, str) for v in c.values()) for c in ctx):
        problems.append("contexts가 [{doc_id, text}] 모양이 아님")
    if not isinstance(trace, list) or not all(isinstance(t, dict) and set(t) == {"step", "input", "output"} and all(isinstance(v, str) for v in t.values()) for t in trace):
        problems.append("trace가 [{step, input, output}] 모양이 아님")
    return problems


def missing_tools(expected: list[str], steps: list[str]) -> list[str]:
    """expected가 steps에 순서대로(사이에 다른 단계가 끼어도 됨) 나타나지 않을 때, 나타나지 않은 도구 이름들."""
    pos = 0
    missing = []
    for tool in expected:
        try:
            pos = steps.index(tool, pos) + 1
        except ValueError:
            missing.append(tool)
    return missing


def case_passed(result: dict) -> bool:
    ok = not result["error"] and not result["contract_problems"] and not result["missing_tools"]
    if result.get("judge") is not None:
        j = result["judge"]
        ok = ok and not j["traits_unmet"] and not j["forbidden_hit"]
    return ok


def is_error(result: dict) -> bool:
    """서비스 답이 틀린 것이 아니라 실행 자체가 안 된 경우(모델 한도·서버 오류·판정 실패). 통과·실패로 세지 말고 다시 돌려야 한다."""
    return bool(result["error"])


def summarize(results: list[dict]) -> dict:
    """카테고리별과 전체 통과 수, 평균 시간, 실행 오류 수. 반복 실행이면 실행 하나하나를 센다."""
    by_cat: dict[str, list[bool]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r["passed"])
    total = [r["passed"] for r in results]
    return {
        "total": {"passed": sum(total), "count": len(total)},
        "by_category": {c: {"passed": sum(v), "count": len(v)} for c, v in sorted(by_cat.items())},
        "errors": sum(1 for r in results if is_error(r)),
        "ragas": average([r.get("ragas") for r in results]),
        "avg_seconds": round(sum(r["seconds"] for r in results) / len(results), 1) if results else 0,
    }


def render_markdown(results: list[dict], title: str) -> str:
    s = summarize(results)
    lines = [f"# {title}", "", f"- 통과 {s['total']['passed']}/{s['total']['count']}, 평균 {s['avg_seconds']}초/건"]
    if s["errors"]:
        lines.append(f"- **실행 오류 {s['errors']}건** (모델 한도 등으로 실행이 안 된 것, 실패가 아니라 다시 돌려야 함)")
    lines.append("")
    lines += ["| 분류 | 통과 |", "|---|---|"] + [f"| {c} | {v['passed']}/{v['count']} |" for c, v in s["by_category"].items()] + [""]
    if any(v["n"] for v in s["ragas"].values()):
        lines += ["검색된 문서가 있는 케이스만 계산한 RAGAS 지표 (평균, 계산한 케이스 수):", "", "| 지표 | 평균 | 케이스 수 |", "|---|---|---|"]
        lines += [f"| {m} | {v['mean'] if v['mean'] is not None else '-'} | {v['n']} |" for m, v in s["ragas"].items()] + [""]
    lines += ["| # | 분류 | 결과 | 도구 | 실패 이유 | 질문 |", "|---|---|---|---|---|---|"]
    for r in results:
        why = "; ".join(reason_list(r)) or "-"
        tools = "→".join(r["steps"]) if r["steps"] else "-"
        lines.append(f"| {r['id']} | {r['category']} | {'통과' if r['passed'] else ('오류' if is_error(r) else '**실패**')} | {tools} | {why} | {r['input'][:40].replace('|', '/')} |")
    return "\n".join(lines) + "\n"


def reason_list(r: dict) -> list[str]:
    out = []
    if r["error"]:
        out.append("오류 " + r["error"])
    out += r["contract_problems"]
    if r["missing_tools"]:
        out.append("빠진 도구 " + ",".join(r["missing_tools"]))
    j = r.get("judge")
    if j:
        out += ["기대 미충족: " + t for t in j["traits_unmet"]] + ["금지 위반: " + f for f in j["forbidden_hit"]]
    return out


# --- 실행 ---------------------------------------------------------------------------------

def run_case(case: dict, retriever, judge_fn=None, scorer=None) -> dict:
    from fastapi.testclient import TestClient

    from src.api import create_app
    from src.store import SqliteStore

    expected = split_items(case["expected_tools"])
    result = {
        "id": case["id"], "category": case["category"], "input": case["input"], "expected_tools": expected,
        "steps": [], "trace": [], "answer": "", "contexts": [], "error": "", "contract_problems": [], "missing_tools": [],
        "judge": None, "ragas": None, "ragas_error": "", "seconds": 0.0,
    }
    start = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            app = create_app(retriever=retriever, store=SqliteStore(Path(tmp) / "eval.db"))
            with TestClient(app) as client:
                resp = client.post("/query", json={"question": case["input"]})
            if resp.status_code != 200:
                result["error"] = f"HTTP {resp.status_code}: {resp.text[:120]}"
            else:
                body = resp.json()
                result["contract_problems"] = contract_problems(body)
                if not result["contract_problems"]:
                    result["steps"] = [t["step"] for t in body["trace"]]
                    result["trace"] = body["trace"]
                    result["answer"], result["contexts"] = body["answer"], body["contexts"]
                    result["missing_tools"] = missing_tools(expected, result["steps"])
        except Exception as e:  # 한 케이스의 오류가 전체 평가를 멈추지 않게 한다
            result["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    result["seconds"] = round(time.time() - start, 1)
    if judge_fn and result["answer"] and not result["error"]:
        try:
            result["judge"] = judge_fn(case, result["answer"], result["trace"], result["contexts"])
        except Exception as e:
            result["error"] = f"판정 실패 {type(e).__name__}: {str(e)[:100]}"
    if scorer and result["answer"] and result["contexts"] and not result["error"]:
        try:  # RAGAS 지표는 통과·실패에 영향을 주지 않는다. 계산 실패는 따로 적는다.
            from evaluation.ragas_metrics import split_reference

            result["ragas"] = scorer.score(case["input"], result["answer"], result["contexts"], split_reference(case["expected_traits"]))
        except Exception as e:
            result["ragas_error"] = f"{type(e).__name__}: {str(e)[:100]}"
    result["passed"] = case_passed(result)
    return result


PLAN_MENU = re.compile(r"^\s*\d+\.\s+(.+?)\s+-\s+\d+세트", re.M)


def plan_menu_names(answer: str) -> list[str]:
    """계획 답변에서 연습 메뉴 이름만 코드로 뽑는다. 긴 계획을 읽다 놓치는 판정 오차를 줄이려고 판정 입력에 따로 준다."""
    return list(dict.fromkeys(PLAN_MENU.findall(answer)))


def make_judge():
    """답변이 기대 항목을 충족하고 금지 항목을 어기지 않았는지 모델이 판정한다. 규칙 계산은 하지 않고 글의 내용만 본다."""
    from langchain_core.prompts import ChatPromptTemplate
    from pydantic import BaseModel, Field

    from src.llm import structured_chain

    class Verdict(BaseModel):
        traits_unmet: list[str] = Field(default_factory=list, description="답변이 충족하지 못한 기대 항목 (원문 그대로)")
        forbidden_hit: list[str] = Field(default_factory=list, description="답변이 어긴 금지 항목 (원문 그대로)")

    prompt = ChatPromptTemplate.from_messages([
        ("system", "당신은 농구 연습 계획 서비스의 답변을 채점하는 평가자입니다. 답변 글, 서비스가 실행한 단계(trace), 근거로 쓴 문서 목록을 보고 판단합니다.\n"
                   "- 기대 항목은 답변 글이나 trace·근거 문서로 확인되는데 충족하지 못했을 때만 traits_unmet에 원문 그대로 적습니다. "
                   "'준비된 문서 근거', '존댓말'처럼 글만으로 드러나지 않는 항목은 trace·근거 문서가 뒷받침하고 답변이 어긋나지 않으면 충족입니다. "
                   "같은 뜻을 다른 말로 썼으면(예: 합산 결과를 '성공률 40%'로 표기) 충족입니다.\n"
                   "- 금지 항목은 답변이 실제로 어겼을 때만 forbidden_hit에 적습니다. '골대 없이 하는 연습'은 골대가 필요한 연습이 아닙니다.\n"
                   "- 답변이 거절·안내 문구라면 그 거절이 항목의 취지에 맞는지로 판단합니다. 모두 지켰으면 두 목록 모두 빈 목록입니다."),
        ("human", "질문: {question}\n\n답변:\n{answer}\n\n실행한 단계(trace):\n{trace}\n\n근거 문서: {docs}\n\n계획에 포함된 연습 메뉴 이름(코드가 답변에서 뽑음): {menus}\n\n기대 항목:\n{traits}\n\n금지 항목:\n{forbidden}"),
    ])
    chain = structured_chain(prompt, Verdict)

    def judge(case: dict, answer: str, trace: list[dict], contexts: list[dict]) -> dict:
        traits, forbidden = split_items(case["expected_traits"]), split_items(case["forbidden"])
        v = chain.invoke({
            "question": case["input"], "answer": answer,
            "trace": "\n".join(f"- {s['step']}: {s['output'][:150]}" for s in trace) or "(없음)",
            "docs": ", ".join(c["doc_id"] for c in contexts) or "(없음)",
            "menus": ", ".join(plan_menu_names(answer)) or "(계획 아님)",
            "traits": "\n".join(f"- {t}" for t in traits) or "(없음)",
            "forbidden": "\n".join(f"- {f}" for f in forbidden) or "(없음)",
        })
        return {"traits_unmet": [t for t in v.traits_unmet if t], "forbidden_hit": [f for f in v.forbidden_hit if f]}

    return judge


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", help="실행할 케이스 id (쉼표로 구분). 없으면 전체")
    ap.add_argument("--repeat", type=int, default=1, help="케이스마다 반복 횟수 (모델 출력이 매번 달라서 통과율을 보려면 3 이상)")
    ap.add_argument("--judge", action="store_true", help="기대 항목·금지 항목을 모델로 판정")
    ap.add_argument("--ragas", action="store_true", help="검색된 문서가 있는 케이스에 RAGAS 네 지표를 계산 (통과 여부에는 영향 없음)")
    ap.add_argument("--out", help="결과 JSON 저장 경로")
    ap.add_argument("--report", help="마크다운 표 저장 경로")
    ap.add_argument("--no-retriever", action="store_true", help="검색 없이 실행 (빠른 점검용)")
    args = ap.parse_args(argv)

    cases = load_cases(ids=set(args.ids.split(",")) if args.ids else None)
    if not cases:
        print("실행할 케이스가 없습니다.")
        return 2
    retriever = None
    if not args.no_retriever:
        from src.retriever import MenuRetriever

        retriever = MenuRetriever()
        retriever.build()
    judge_fn = make_judge() if args.judge else None
    scorer = None
    if args.ragas:
        from evaluation.ragas_metrics import make_scorer

        scorer = make_scorer()

    results = []
    for case in cases:
        for n in range(args.repeat):
            r = run_case(case, retriever, judge_fn, scorer)
            r["run"] = n + 1
            results.append(r)
            mark = "통과" if r["passed"] else ("오류" if is_error(r) else "실패")
            why = "; ".join(reason_list(r))
            print(f"{r['id']:>3} {mark} {r['seconds']:>5}s {r['category']:<9} {r['input'][:34]}" + (f"  <- {why}" if why else ""), flush=True)
    s = summarize(results)
    print(f"\n통과 {s['total']['passed']}/{s['total']['count']}  평균 {s['avg_seconds']}초/건")
    if s["errors"]:
        print(f"주의: 실행 오류 {s['errors']}건은 모델 한도 등으로 실행이 안 된 것입니다. 실패로 보지 말고 --ids로 다시 돌리세요.")
    for c, v in s["by_category"].items():
        print(f"  {c:<10} {v['passed']}/{v['count']}")
    if args.ragas:
        print("RAGAS 지표 (평균, 계산한 케이스 수):")
        for m, v in s["ragas"].items():
            print(f"  {m:<18} {v['mean'] if v['mean'] is not None else '-'}  (n={v['n']})")
        failed = [r["id"] for r in results if r["ragas_error"]]
        if failed:
            print(f"  RAGAS 계산 실패 케이스: {', '.join(failed)}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"summary": s, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(render_markdown(results, "평가 결과"), encoding="utf-8")
    return 0 if s["total"]["passed"] == s["total"]["count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
