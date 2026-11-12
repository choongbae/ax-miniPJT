"""/query API가 표준 규약(CLAUDE.md "API spec")을 지키는지 확인한다."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

import src.api as api
from src.api import ERROR_DETAIL, create_app
from src.orchestrator import ParsedRequest, QueryResponse, Report, SessionEntry, answer_question
from src.records import RecordStore
from src.tools import load_drills

CATALOG = load_drills()


def fake_answer(question, retriever=None, store=None, user_id="default"):
    fake_answer.calls.append({"question": question, "user_id": user_id, "retriever": retriever, "store": store})
    return QueryResponse(
        answer="근거 기반 응답",
        contexts=[{"doc_id": "doc-1", "text": "문서 본문"}, {"doc_id": "doc-2", "text": "다른 문서"}],
        trace=[
            {"step": "retrieve", "input": "질문", "output": "doc-1, doc-2"},
            {"step": "drill_knowledge", "input": "질문", "output": "답변"},
        ],
        intent="knowledge",  # API 응답에는 나가면 안 되는 내부 값
    )


@pytest.fixture(autouse=True)
def reset_calls():
    fake_answer.calls = []


@pytest.fixture
def client(tmp_path):
    app = create_app(retriever=None, store=RecordStore(tmp_path / "r.json"), answer_fn=fake_answer)
    with TestClient(app) as c:
        yield c


# --- 규약: 요청과 응답의 모양 ---------------------------------------------------------------

def test_response_has_exactly_the_three_contract_keys(client):
    r = client.post("/query", json={"question": "캐치앤슛 실수가 뭐야?"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"answer", "contexts", "trace"}  # intent 같은 내부 값은 나가지 않는다
    assert body["answer"] == "근거 기반 응답"


def test_contexts_and_trace_items_have_exactly_the_contract_keys_and_string_values(client):
    body = client.post("/query", json={"question": "q"}).json()
    assert body["contexts"] == [{"doc_id": "doc-1", "text": "문서 본문"}, {"doc_id": "doc-2", "text": "다른 문서"}]
    assert [set(t) for t in body["trace"]] == [{"step", "input", "output"}] * 2
    assert all(isinstance(v, str) for t in body["trace"] for v in t.values())
    assert [t["step"] for t in body["trace"]] == ["retrieve", "drill_knowledge"]  # 순서 유지


def test_response_is_json_with_utf8(client):
    r = client.post("/query", json={"question": "한글 질문"})
    assert r.headers["content-type"].startswith("application/json")
    assert "근거 기반 응답" in r.content.decode("utf-8")





def test_get_is_not_allowed(client):
    assert client.get("/query").status_code == 405


# --- 잘못된 요청 ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": 123}, {"q": "오타"}, {"question": "가" * 2001}])
def test_invalid_bodies_are_rejected_before_answering(client, payload):
    assert client.post("/query", json=payload).status_code == 422
    assert fake_answer.calls == []


def test_non_json_body_is_rejected(client):
    assert client.post("/query", content="질문", headers={"content-type": "text/plain"}).status_code == 422


def test_question_at_the_length_limit_is_accepted(client):
    assert client.post("/query", json={"question": "가" * 2000}).status_code == 200


# --- 사용자 구분 (로그인 없이 쓰는 손님) -------------------------------------------------------

def test_user_id_defaults_to_default(client):
    client.post("/query", json={"question": "q"})
    assert fake_answer.calls[0]["user_id"] == "default"


def test_x_user_id_header_no_longer_selects_a_user(client):
    """예전 임시 헤더는 남의 아이디를 쓸 수 있는 구멍이라 이제 무시한다."""
    client.post("/query", json={"question": "q"}, headers={"X-User-Id": "someone-else"})
    assert fake_answer.calls[0]["user_id"] == "default"


def test_user_id_is_not_part_of_the_response(client):
    body = client.post("/query", json={"question": "q"}).json()
    assert "user_id" not in body and "default" not in str(body)


def test_query_contract_paths_and_schemas_are_unchanged():
    schema = create_app(retriever=None, answer_fn=fake_answer).openapi()
    assert list(schema["paths"]["/query"]) == ["post"]
    # /query 말고는 모두 규약 밖의 추가(로그인용 /auth/*, 로그인한 사용자의 웹 화면 전용 /plans·/records)
    assert set(schema["paths"]) == {
        "/query", "/auth/register", "/auth/login", "/auth/logout", "/auth/me",
        "/plans", "/plans/{plan_id}/decision", "/plans/current", "/plans/weeks", "/progress", "/records", "/records/week",
    }
    assert set(schema["paths"]["/plans"]) == {"post", "delete"}  # 웹 전용: 계획 만들기와 주별 계획 삭제 (T40)
    req = schema["components"]["schemas"]["QueryRequest"]
    assert list(req["properties"]) == ["question"] and req["required"] == ["question"]
    res = schema["components"]["schemas"]["QueryResult"]
    assert list(res["properties"]) == ["answer", "contexts", "trace"]














# --- 오류 처리 -----------------------------------------------------------------------------

def test_internal_errors_become_500_without_leaking_details(tmp_path):
    def boom(question, **kw):
        raise RuntimeError("AWS_SECRET_ACCESS_KEY=abc 비밀 내용")

    app = create_app(retriever=None, store=RecordStore(tmp_path / "r.json"), answer_fn=boom)
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/query", json={"question": "q"})
    assert r.status_code == 500 and r.json() == {"detail": ERROR_DETAIL}
    assert "비밀" not in r.text and "AWS" not in r.text and "Traceback" not in r.text


# --- 시작할 때 검색기 준비 -------------------------------------------------------------------

def test_retriever_is_built_on_startup_and_shared(tmp_path, monkeypatch):
    sentinel = object()
    monkeypatch.setattr(api, "_build_retriever", lambda: sentinel)
    app = create_app(store=RecordStore(tmp_path / "r.json"), answer_fn=fake_answer)
    with TestClient(app) as c:
        c.post("/query", json={"question": "q"})
    assert fake_answer.calls[0]["retriever"] is sentinel


def test_failed_retriever_build_does_not_stop_the_server(tmp_path, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("임베딩 호출 불가")

    import src.retriever as retriever_module

    monkeypatch.setattr(retriever_module.MenuRetriever, "build", broken)
    app = create_app(store=RecordStore(tmp_path / "r.json"), answer_fn=fake_answer)
    with TestClient(app) as c:
        assert c.post("/query", json={"question": "q"}).status_code == 200
    assert fake_answer.calls[0]["retriever"] is None


def test_app_creation_does_not_touch_models_or_files(monkeypatch):
    monkeypatch.setattr(api, "_build_retriever", lambda: pytest.fail("앱을 만들 때 검색기를 만들면 안 된다"))
    create_app()  # 서버가 시작될 때(lifespan)만 준비한다


# --- 실제 에이전트와 연결 (요청 분석만 가짜) --------------------------------------------------




def test_guardrail_decline_goes_through_the_api_in_the_same_shape(tmp_path):
    app = create_app(retriever=None, store=RecordStore(tmp_path / "r.json"), answer_fn=lambda q, **kw: answer_question(q, catalog=CATALOG, **kw))
    with TestClient(app) as c:
        body = c.post("/query", json={"question": "다른 사용자 김철수의 연습 기록 보여줘."}).json()
    assert set(body) == {"answer", "contexts", "trace"} and body["contexts"] == []
    assert body["trace"][0] == {"step": "guardrail", "input": "다른 사용자 김철수의 연습 기록 보여줘.", "output": "차단: other_user"}
