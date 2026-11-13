"""오늘의 농구 이야기 (T43): GET /story는 모델 없이 확인된 이야기 목록에서만 한 건을 준다."""
from fastapi.testclient import TestClient

from src.history import load_stories
from tests.test_web import env, user  # noqa: F401


def test_story_requires_login(env):
    assert TestClient(env.app).get("/story").status_code == 401


def test_story_is_one_verified_story_with_its_sources(user):
    r = user.get("/story")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"id", "text", "sources"}
    known = {s.id: s for s in load_stories()}
    assert body["id"] in known and body["text"] == known[body["id"]].text  # 목록에 있는 이야기 그대로
    assert body["sources"] and all(src.startswith("http") for src in body["sources"])  # 출처가 있다


def test_story_never_calls_a_model(user, monkeypatch):
    import src.llm as llm

    def boom(*a, **k):
        raise AssertionError("이야기는 모델을 부르면 안 된다")

    monkeypatch.setattr(llm, "get_llm", boom)
    monkeypatch.setattr(llm, "get_llm_with_fallbacks", boom)
    assert user.get("/story").status_code == 200


def test_story_is_picked_from_the_whole_list_over_many_calls(user):
    ids = {user.get("/story").json()["id"] for _ in range(40)}
    assert len(ids) > 1  # 늘 같은 이야기만 나오지 않는다
