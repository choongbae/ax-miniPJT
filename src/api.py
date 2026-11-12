"""HTTP API. /query는 표준 규약(CLAUDE.md "API spec")을 그대로 따른다.

    POST /query
    Body:     {"question": "사용자 질의"}
    Response: {"answer": "...", "contexts": [{"doc_id": "...", "text": "..."}],
               "trace": [{"step": "...", "input": "...", "output": "..."}]}

규약에 없는 키는 /query의 요청에도 응답에도 더하지 않는다.

사용자 구분(T25): 로그인하면 세션 토큰을 받는다. 토큰은 쿠키(session, HttpOnly)나 `Authorization: Bearer <토큰>` 헤더로 보낸다.
- 토큰이 없으면 손님 계정(default)으로 처리한다. 본문만으로 호출하는 규약과 평가 실행을 위해서다.
- 토큰이 있는데 잘못되었거나 만료되었으면 손님으로 넘기지 않고 401로 거절한다.
계정 엔드포인트(/auth/*)와 웹 화면 전용 엔드포인트(src/web.py)는 규약 밖의 추가이며, 후자는 로그인이 필요하다.

실행: uvicorn src.api:app
"""
import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.agent import generate_plan
from src.auth import GUEST_ID, SESSION_DAYS, AuthError, AuthService
from src.orchestrator import answer_question
from src.web import add_web_routes
from src.store import DEFAULT_DB_PATH, SqliteStore

logger = logging.getLogger(__name__)

_UNSET = object()
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
# 화면(HTML·JS·CSS)에만 적용하는 보안 헤더. 인라인 스크립트와 다른 사이트의 리소스를 막는다. (/docs의 Swagger UI에는 적용하지 않는다)
PAGE_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}
SESSION_COOKIE = "session"
ERROR_DETAIL = "일시적인 오류로 답변하지 못했어요. 잠시 뒤에 다시 시도해 주세요."
LOGIN_REQUIRED_DETAIL = "로그인이 필요하거나 로그인이 만료되었어요. 다시 로그인해 주세요."


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class ContextItem(BaseModel):
    doc_id: str
    text: str


class TraceStep(BaseModel):
    step: str
    input: str
    output: str


class QueryResult(BaseModel):
    answer: str
    contexts: list[ContextItem]
    trace: list[TraceStep]


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class UserInfo(BaseModel):
    username: str


class LoginResult(BaseModel):
    username: str
    token: str  # 브라우저는 쿠키로, 다른 클라이언트는 이 값을 Bearer 헤더로 쓴다


def _build_retriever():
    """연습 메뉴·안내 문서 검색기를 준비한다. 실패해도(임베딩 호출 불가 등) 서버는 뜨고, 검색 없이 답한다."""
    try:
        from src.retriever import MenuRetriever

        retriever = MenuRetriever()
        retriever.build()
        return retriever
    except Exception:
        logger.exception("검색기를 준비하지 못해 검색 없이 시작합니다")
        return None


def _token_of(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(SESSION_COOKIE)


def create_app(
    retriever=_UNSET,
    store=None,
    answer_fn=answer_question,
    auth: AuthService | None = None,
    cookie_secure: bool | None = None,
    generate_fn=generate_plan,
    today=date.today,
    now=None,
) -> FastAPI:
    """앱을 만든다. retriever, store, answer_fn, auth, generate_fn(계획 생성), today는 테스트에서 바꿔 끼울 수 있다."""
    secure = cookie_secure if cookie_secure is not None else os.getenv("COOKIE_SECURE") == "1"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.retriever = _build_retriever() if retriever is _UNSET else retriever
        app.state.store = store if store is not None else SqliteStore(DEFAULT_DB_PATH)
        # 계정 기능은 계정을 저장할 수 있는 저장소(SqliteStore)일 때만 켠다
        app.state.auth = auth or (AuthService(app.state.store) if hasattr(app.state.store, "create_user") else None)
        yield

    app = FastAPI(title="농구 연습 계획 Agent", lifespan=lifespan)

    def current_user(request: Request) -> str:
        """토큰이 없으면 손님, 있으면 그 사용자. 잘못되었거나 만료된 토큰은 401."""
        token = _token_of(request)
        if token is None or app.state.auth is None:
            return GUEST_ID
        username = app.state.auth.user_for_token(token)
        if username is None:
            raise HTTPException(status_code=401, detail=LOGIN_REQUIRED_DETAIL)
        return username

    def need_auth() -> AuthService:
        if app.state.auth is None:
            raise HTTPException(status_code=501, detail="이 저장소는 계정을 지원하지 않습니다.")
        return app.state.auth

    # --- 표준 규약 ---------------------------------------------------------------
    @app.post("/query", response_model=QueryResult)
    def query(body: QueryRequest, request: Request) -> QueryResult:
        user_id = current_user(request)
        try:
            resp = answer_fn(body.question, retriever=app.state.retriever, store=app.state.store, user_id=user_id)
        except Exception:
            logger.exception("질문 처리 실패")
            raise HTTPException(status_code=500, detail=ERROR_DETAIL)  # 내부 오류 내용은 응답에 싣지 않는다
        return QueryResult(
            answer=resp.answer,
            contexts=[ContextItem(doc_id=c["doc_id"], text=c["text"]) for c in resp.contexts],
            trace=[TraceStep(step=t["step"], input=t["input"], output=t["output"]) for t in resp.trace],
        )

    # --- 계정 (규약 밖) -------------------------------------------------------------
    @app.post("/auth/register", response_model=UserInfo, status_code=201)
    def register(body: Credentials) -> UserInfo:
        try:
            return UserInfo(username=need_auth().register(body.username, body.password))
        except AuthError as e:
            raise HTTPException(status_code=e.status, detail=e.message)

    @app.post("/auth/login", response_model=LoginResult)
    def login(body: Credentials, response: Response) -> LoginResult:
        try:
            username, token = need_auth().login(body.username, body.password)
        except AuthError as e:
            raise HTTPException(status_code=e.status, detail=e.message)
        response.set_cookie(
            SESSION_COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax", secure=secure
        )
        return LoginResult(username=username, token=token)

    @app.post("/auth/logout", status_code=204)
    def logout(request: Request, response: Response) -> None:
        if app.state.auth is not None:
            app.state.auth.logout(_token_of(request))
        response.delete_cookie(SESSION_COOKIE)

    @app.get("/auth/me", response_model=UserInfo)
    def me(request: Request) -> UserInfo:
        username = current_user(request)
        if username == GUEST_ID:
            raise HTTPException(status_code=401, detail=LOGIN_REQUIRED_DETAIL)
        return UserInfo(username=username)

    # --- 웹 화면 전용 (규약 밖, 로그인 필요) --------------------------------------------
    add_web_routes(app, current_user, GUEST_ID, generate_fn, today, **({"now": now} if now else {}))

    # --- 화면 파일 -----------------------------------------------------------------
    @app.middleware("http")
    async def page_security_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            for name, value in PAGE_HEADERS.items():
                response.headers[name] = value
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html", media_type="text/html; charset=utf-8")

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    return app


app = create_app()
