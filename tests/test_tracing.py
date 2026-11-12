"""트레이싱 (T28): 외부 트레이스로 나가는 입력에서 사용자 ID와 객체를 줄이는지 확인한다. (실제 전송은 하지 않는다)"""
import os

from src.tracing import anonymize, traced


def test_tests_never_upload_traces():
    assert os.environ["LANGSMITH_TRACING"] == "false"


def test_user_ids_are_hashed_and_stable():
    a = anonymize("minsu")
    assert a.startswith("user-") and "minsu" not in a and a == anonymize("minsu") and a != anonymize("jisu")


def test_traced_functions_keep_their_behavior():
    @traced("t", keep=("question",))
    def f(question, user_id="default", store=None):
        return question + user_id

    assert f("q", user_id="minsu", store=object()) == "qminsu"


def test_only_kept_inputs_and_a_hashed_user_are_sent(monkeypatch):
    seen = {}

    def fake_traceable(name, run_type, process_inputs):
        def wrap(fn):
            seen["inputs"] = process_inputs({"question": "q", "user_id": "minsu", "store": object(), "known_user_ids": ["minsu", "jisu"]})
            return fn

        return wrap

    import src.tracing as tracing

    monkeypatch.setattr(tracing, "traceable", fake_traceable)
    traced("x", keep=("question",))(lambda: None)
    assert set(seen["inputs"]) == {"question", "user"} and "minsu" not in str(seen["inputs"])
