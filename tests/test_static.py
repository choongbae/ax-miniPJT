"""웹 화면 파일(web/)이 안전하게 제공되고, 화면 코드가 위험한 방식을 쓰지 않는지 확인한다."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import WEB_DIR, create_app
from src.store import SqliteStore

SVG_NAMESPACE = "http://www.w3.org/2000/svg"  # 그래프를 그릴 때 요소를 만드는 데 쓰는 이름공간 식별자
APP_JS = (WEB_DIR / "app.js").read_text(encoding="utf-8")
INDEX = (WEB_DIR / "index.html").read_text(encoding="utf-8")
CSS = (WEB_DIR / "style.css").read_text(encoding="utf-8")
# 위험한 코드 검사는 주석을 뺀 실제 코드만 본다 (주석에 '쓰지 않는다'고 적은 글자는 위반이 아니다)
APP_JS_CODE = re.sub(r"^\s*//.*$", "", re.sub(r"/\*.*?\*/", "", APP_JS, flags=re.S), flags=re.M)


@pytest.fixture
def client(tmp_path):
    app = create_app(retriever=None, store=SqliteStore(tmp_path / "a.db"))
    with TestClient(app) as c:
        yield c


# --- 제공 -------------------------------------------------------------------------------

def test_root_serves_the_page(client):
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert '<html lang="ko">' in r.text and "<title>농구 연습 계획</title>" in r.text
    assert 'name="viewport"' in r.text  # 모바일 폭


def test_assets_are_served(client):
    js, css = client.get("/static/app.js"), client.get("/static/style.css")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")


def test_page_and_assets_have_security_headers(client):
    for path in ("/", "/static/app.js", "/static/style.css"):
        h = client.get(path).headers
        csp = h["content-security-policy"]
        assert "default-src 'self'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert "'unsafe-inline'" not in csp and "'unsafe-eval'" not in csp
        assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer"


def test_api_docs_and_json_responses_are_not_broken_by_the_page_policy(client):
    assert client.get("/docs").status_code == 200
    assert "content-security-policy" not in client.get("/docs").headers  # Swagger UI는 인라인 스크립트를 쓴다
    assert "content-security-policy" not in client.post("/query", json={"question": "트래블링이 뭐야?"}).headers


@pytest.mark.parametrize("path", ["/static/../src/api.py", "/static/%2e%2e/src/api.py", "/static/..%2fsrc%2fapi.py", "/static/missing.js", "/static/"])
def test_static_cannot_read_anything_outside_the_web_folder(client, path):
    r = client.get(path)
    assert r.status_code == 404 and "FastAPI" not in r.text and "create_app" not in r.text


def test_only_the_expected_files_are_in_the_web_folder():
    assert sorted(p.name for p in WEB_DIR.iterdir()) == ["app.js", "index.html", "style.css"]


# --- 화면 코드가 위험한 방식을 쓰지 않는다 ---------------------------------------------------

@pytest.mark.parametrize("danger", ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setTimeout(\"", "javascript:"])
def test_app_js_never_builds_html_from_strings(danger):
    """계획·안내·이야기 글은 모델이 만든 것이라, HTML로 해석되지 않게 textContent·텍스트 노드로만 그려야 한다."""
    assert danger not in APP_JS_CODE


def test_the_comment_stripping_in_this_test_really_removes_comments():
    assert "innerHTML" in APP_JS and "innerHTML" not in APP_JS_CODE  # 주석에만 있고 코드에는 없다


def test_page_has_no_inline_scripts_or_handlers():
    assert not re.search(r"<script(?![^>]*\bsrc=)", INDEX)  # 모든 script는 src가 있다
    assert not re.search(r"\son[a-z]+\s*=", INDEX)  # onclick= 같은 인라인 핸들러 없음
    assert "style=" not in INDEX  # 인라인 스타일 없음 (CSP style-src 'self')


def test_no_external_resources():
    for name, text in (("index.html", INDEX), ("app.js", APP_JS), ("style.css", CSS)):
        urls = re.findall(r"https?://[^\s\"')]+", text)
        urls = [u for u in urls if u != SVG_NAMESPACE]  # SVG 이름공간은 요청을 보내는 주소가 아니라 식별자다
        assert urls == [], f"{name}에 외부 주소가 있다: {urls}"


def test_all_requests_go_to_the_same_server():
    assert re.findall(r'fetch\(\s*["\'`]?(https?:)', APP_JS) == []
    for path in re.findall(r'api\(\s*"([^"]+)"', APP_JS):
        assert path.startswith("/"), path
    assert 'credentials: "same-origin"' in APP_JS


def test_page_loads_with_expected_endpoints_wired():
    for path in ("/auth/me", "/auth/login", "/auth/register", "/auth/logout", "/plans/current", "/plans"):
        assert path in APP_JS, path


def test_every_form_input_has_a_label():
    # 아이디·비밀번호·포지션·약점·일수·시간 입력은 모두 label for=와 연결된다
    for field_id in ("username", "password", "position", "goals", "days", "minutes", "beginner"):
        assert f'for: "{field_id}"' in APP_JS, field_id


def test_the_beginner_option_is_shown_only_for_the_first_plan():
    """'농구를 처음 시작했어요'는 계획이 하나도 없는 사용자에게만 보인다 (T38). 동작은 실제 브라우저 확인, 여기서는 연결을 본다."""
    assert "setFirstPlan(info.weeks.length === 0)" in APP_JS  # 주 목록을 불러올 때마다(첫 화면, 계획 확정 뒤) 맞춘다
    assert "beginnerLabel.hidden = !isFirst" in APP_JS
