# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

Work is tracked in `TASKS.md` (bundles 1 and 2 done: CLI path from input to validated plan, difficulty rules, record store, beginner option; bundle 3 done: menu and guide documents, hybrid retrieval, retrieval wired into planning, knowledge tool, history tool; bundle 4 mostly done: question-level agent (T20), guardrails (T21, T22), per-user weekly plans and automatic use of last week's records (T24); the `/query` API is done too (T20-1, FastAPI, `src/api.py`); bundle 5 has started: login and SQLite storage are done (T25), the web screens (T26, T27) and plan approval via LangGraph `interrupt()` (T26-1: `POST /plans` makes an unsaved draft, `POST /plans/{id}/decision` confirms or rejects it, drafts expire after 24h, state in `data/checkpoints.db`) are done too; tracing is done (T28, `src/tracing.py`, LangSmith project `basketball-practice-agent`, user IDs hashed, off in tests); evaluation runner is done (T29: `python -m evaluation.run_eval`, 32 cases through `/query`; round 1 evaluation (T30, 23/32, `evaluation/round1_report.md`) and the in-house RAGAS metrics (T32, `evaluation/ragas_metrics.py`, no ragas library) are done; fixes and round 2 (T31, 93/96 over 3 repeats) are done; bundle 7 (web extensions) has started: week navigation (T34) and the reset of records when a plan is regenerated (T35: confirming a draft that replaces an existing plan deletes that week's records, with a count warning and a second confirmation in the UI) are done, the per-area progress screen (T36: `src/progress.py`, `GET /progress`, the 분야별 현황 tab with SVG charts) are done too; bundle 8 (web polish, T37 to T40) has started: the save indicators on record cards (T37) and the first-plan-only beginner option (T38, shown only while the user has no plan in any week) are done; the keep-and-recommend rule for the hardest menus (T39: `src/recommend.py`, rule-based, no model) are done; the plan delete button with a confirm dialog (T40, `DELETE /plans?week=`, also deletes that week's records) is done too; the README wrap-up (T33) is the last open task and should mention bundles 7 and 8). Python packages live in the shared venv one level up (`../.venv`); `requirements.txt` pins what the code uses.

Commands (run from the repo root):
- Tests: `python -m pytest tests -q`. One test: `python -m pytest tests/test_adjust.py::test_case3_lower_requires_replacing_with_easier_shot_menu -q`.
- CLI: `python -m src.agent [--user NAME]` (asks the beginner question only for users with no stored records). Calls Bedrock, so it needs `.env`.
- API: `uvicorn src.api:app` (FastAPI, `POST /query`). Users are identified by a login session: the `session` HttpOnly cookie or an `Authorization: Bearer <token>` header. No token means the shared guest user `default` (the contract takes only a body, so graders and the evaluation runner work without logging in); a token that is present but invalid or expired gets 401, never guest. Accounts live in SQLite (`data/app.db`, gitignored) behind `/auth/register`, `/auth/login`, `/auth/logout`, `/auth/me`; these are extra endpoints outside the `/query` contract and exist only for login. The old `X-User-Id` header was removed because it allowed impersonation. The server builds the retriever at startup and still starts without it if that fails. Tests use `fastapi.testclient.TestClient`.
- Model smoke call: `python -m src.llm`. The model ID defaults in `src/llm.py` and can be overridden with `BEDROCK_MODEL_ID` in `.env`.

Code map (read together): `src/tools.py` (input and plan validation, difficulty judgments, equipment notices), `src/adjust.py` (turn last week's judgments into prompt text and checks), `src/records.py` (record validation, JSON store with per-user records and per-week plans, `judge_week`), `src/agent.py` (prompt, LangGraph retrieve -> generate -> validate -> retry, CLI), `src/orchestrator.py` (`answer_question`: input guardrail -> LLM request parsing -> tool calls -> output check, returns answer, contexts and a trace whose step names match `expected_tools` in the evaluation set), `src/guardrails.py` (regex input guardrails and output leak check, no model calls), `src/api.py` (the `/query` FastAPI app plus `/auth/*`; the response model keeps internal fields such as `intent` out of the contract), `src/auth.py` (scrypt password hashes, session tokens stored only as SHA-256 hashes, login rate limit, standard library only), `src/store.py` (`SqliteStore`: accounts, sessions, records, weekly plans; same record methods as the JSON `RecordStore`, which tests parametrize over both). Drill data is `data/drills.json` (structured fields, used for validation) plus `data/menus/*.md` (one document per menu with a `doc_id`, indexed for retrieval; `tests/test_menu_docs.py` keeps the two in sync). `src/retriever.py` embeds the documents with Bedrock Titan v2 into Chroma (`chroma_db/`, rebuilt automatically when documents change). The agent graph is retrieve -> generate -> validate -> retry -> finish, and the retrieved documents end up in `state["contexts"]`. `src/llm.py` falls back to another Bedrock model when the default one fails (daily token limit, no permission, retired model). `data/guides/*.md` are general documents (glossary, rules, principles with reasons, warm-up, positions, difficulty rules, beginner guide) with `kind: guide`; planning retrieval only uses `kind: menu`. `src/knowledge.py` answers knowledge questions only from retrieved documents (distance limit 0.7) and says so when there is no evidence; the card summary under each planned menu comes from the menu document by code, not by the LLM. `src/history.py` (history stories) never calls a model: it only serves the stories in `data/history.json`, each with source URLs and a check date, because an LLM-written story passed every format check while being factually wrong (and a second LLM review still let subtle errors through). Requests for exact records or statistics are refused in code. Add a story only after verifying it against sources, and leave out details the sources disagree on. The plan screen shows one story.

## What this is

A course mini-project (SDS AX practice, Day 1~7 curriculum: LangChain/LCEL, RAG, LangGraph, Tool/ToolNode, guardrails, memory/observability/eval). It is a basketball practice-planning agent for solo hobby players: it generates a 1-week training plan, takes manually entered practice records, and adjusts next week's difficulty from them (plan → practice → record → next plan).

Source of truth for requirements, in this order:
- `.ouroboros/pm.md`: PRD with the 14 success criteria. Seed `seed_3540b71d16ce` (Ouroboros) was generated from it.
- `SERVICE.md`: service spec (course template §4-3), including the guardrail summary.
- `README.md`: course template §4-5. Pattern list is a plan; keep only what is actually used. RAGAS, pass-rate and retrospective sections are placeholders.

## Architecture rules that span files

- **Difficulty adjustment is rule-based code in `src/tools.py`, not LLM judgment.** The LLM generates the whole plan, but must receive the computed difficulty as input and obey it.
  - Shot drills (judged per drill; full detail in SERVICE.md section 3): sum attempts and makes over the week. Zero attempts or fewer than 20 attempts keeps. Round the success rate to one decimal; < 40.0% lowers, 40.0% to < 60.0% keeps, >= 60.0% raises. If any of the last 4 weeks (excluding this week, only weeks with >= 20 attempts) reached the boundary (40% or 60%), a rounded rate within 1 percentage point below that boundary is treated as the boundary.
  - Non-shot drills (dribble, layup, pass): the most frequent self-rating of the week. 쉬웠음 raises, 적당 keeps, 어려웠음 lowers. A tie keeps.
  - A drill planned but with no record that week keeps its difficulty and is included again next week.
  - A first-time user's first plan difficulty equals the entered skill level (초급/중급/상급).
- **Plans are validated after generation** (graph step in `src/agent.py`, checks as tools): training days <= N, per-day drill minutes sum <= M, no drill that needs equipment or a place the user said they lack. Violations trigger regeneration.
- **Concrete meaning of raise/lower for shot drills** (used to verify results): lower = shorter distance (3-point line to mid-range) or set shots; raise = moving or catch-and-shoot shots, longer distance, or defensive pressure or a time limit.
- `src/retriever.py` indexes drill documents in `data/` (self-authored fake data) and is required, because README reports RAGAS metrics.

## Scope limits (MVP)

Web browser, login with per-user stored plans and records, after-practice use only, manual record entry only. No video upload or analysis, no real-time use, no form or injury advice. Plan length is fixed at 1 week, availability is input as "N days/week x M minutes/session". Minimize cost; small paid LLM API use is allowed. Demo within a few weeks.

## API spec (standard contract, follow exactly)

Any HTTP API for this agent must use this contract. Do not rename keys, change types, or add required fields; anything extra needs the user's approval first.

```
POST /query
Content-Type: application/json
Body: {"question": "사용자 질의"}

Response:
{
  "answer": "근거 기반 응답",
  "contexts": [{"doc_id": "...", "text": "..."}, ...],
  "trace": [{"step": "retrieve", "input": "...", "output": "..."}, ...]
}
```

- `question` is free natural language (like the inputs in `evaluation/test_queries.csv`), so the agent has to pull position, level, goals, days, minutes and equipment out of the text itself. The structured CLI input is not part of the API.
- `contexts` are the retrieved documents the answer is grounded in (`doc_id`, `text`); the RAGAS metrics read them. Use an empty list when nothing was retrieved.
- `trace` lists the agent steps in order (`step`, `input`, `output`, all strings). The evaluation runner and tracing read it.
- Which user a request belongs to is not in the contract; decide how to pass it (for example an optional header) before building records per user over the API.

## Course deliverable conventions

- The submitted folder name is `mini-pjt_{본인이름}`; this working folder is `mini-pjt`.
- `evaluation/test_queries.csv` is the in/out test set that drives self-evaluation and final grading. Its schema (course §4-4) is not in the repo yet. The SERVICE.md template says `test_queries.json` while the folder layout says `.csv`; unresolved.
- `evaluation/round1_report.md` (Day 9) and `round2_report.md` (Day 10, after improvements) record self-evaluation results.
- `Dockerfile` and `run.sh` are optional and not created.
- `.ouroboros/` and `.claude/` are tooling state, untracked.

## Language

Docs and user-facing text are Korean; keep that when editing them.

# 작업 규칙

- 무엇을 만드는지는 SERVICE.md가 기준이다. 애매하면 추측하지 말고 물어본다.

- 스택: Python, LangGraph, Bedrock (global.anthropic.claude-sonnet-4-5-20250929-v1:0, us-west-2, 대체는 global.anthropic.claude-haiku-4-5-20251001-v1:0) -> 필요 시 모델은 조정해서 사용하거나 복수의 모델을 상황에 맞춰 변경하여 중단없이 쓸 수 있게 한다.

- 괜찮은 레퍼런스 코드를 깃허브에서 찾아서 레퍼런스로 삼거나 (있을 경우) 현재 ref 폴더 내 코드를 참조한다. 절대 사용자의 허락없이 신규 프레임워크 또는 라이브러리를 들이지 않는다.

- 한 번에 TASKS.md의 작업 하나만 한다.

- 계산, 규칙 판정은 LLM이 아니라 파이썬 코드로 하는 원칙으로 진행한다. 필요시 LLM 판정부분을 덧붙여 추가한다.

- API 키는 .env에서 읽는다.
