import pytest
from langchain_core.runnables import RunnableLambda

import src.agent as agent
from src.models import UserInput, WeeklyPlan
from src.tools import load_drills

CATALOG = load_drills()
USER = UserInput(position="가드", level="중급", goals=[], days_per_week=3, minutes_per_session=40, equipment=["골대"])


def plan(name):
    return WeeklyPlan.model_validate(
        {"days": [{"day": "월", "drills": [{"name": name, "sets": 3, "reps": 10, "minutes": 20, "purpose": "p"}]}]}
    )


class FakeModel:
    """with_structured_output만 흉내 내는 가짜 모델. fail이 True이면 호출할 때 오류를 낸다."""

    def __init__(self, result=None, fail=False, error="Too many tokens per day"):
        self.result, self.fail, self.error, self.calls = result, fail, error, 0

    def with_structured_output(self, schema):
        def run(_):
            self.calls += 1
            if self.fail:
                raise RuntimeError(self.error)
            return self.result

        return RunnableLambda(run)


def test_falls_back_to_next_model_when_primary_fails(monkeypatch):
    primary = FakeModel(fail=True)
    backup = FakeModel(result=plan("3점 캐치앤슛"))
    monkeypatch.setattr(agent, "get_llm", lambda: primary)
    monkeypatch.setattr(agent, "get_fallback_llms", lambda: [backup])
    result = agent.generate_plan(USER, CATALOG)
    assert result.days[0].drills[0].name == "3점 캐치앤슛"
    assert primary.calls == 1 and backup.calls == 1


def test_primary_is_used_when_it_works(monkeypatch):
    primary = FakeModel(result=plan("풀업 점퍼"))
    backup = FakeModel(result=plan("3점 캐치앤슛"))
    monkeypatch.setattr(agent, "get_llm", lambda: primary)
    monkeypatch.setattr(agent, "get_fallback_llms", lambda: [backup])
    assert agent.generate_plan(USER, CATALOG).days[0].drills[0].name == "풀업 점퍼"
    assert backup.calls == 0


def test_all_models_failing_raises(monkeypatch):
    monkeypatch.setattr(agent, "get_llm", lambda: FakeModel(fail=True))
    monkeypatch.setattr(agent, "get_fallback_llms", lambda: [FakeModel(fail=True, error="권한 없음")])
    with pytest.raises(RuntimeError):
        agent.generate_plan(USER, CATALOG)


def test_no_fallbacks_configured_uses_primary_only(monkeypatch):
    primary = FakeModel(result=plan("풀업 점퍼"))
    monkeypatch.setattr(agent, "get_llm", lambda: primary)
    monkeypatch.setattr(agent, "get_fallback_llms", lambda: [])
    assert agent.generate_plan(USER, CATALOG).days[0].drills[0].name == "풀업 점퍼"


def test_explicit_llm_is_used_without_fallbacks(monkeypatch):
    monkeypatch.setattr(agent, "get_fallback_llms", lambda: pytest.fail("대체 모델을 만들면 안 된다"))
    explicit = FakeModel(result=plan("풀업 점퍼"))
    assert agent.generate_plan(USER, CATALOG, llm=explicit).days[0].drills[0].name == "풀업 점퍼"


def test_fallback_model_ids_can_be_set_in_env(monkeypatch):
    import src.llm as llm

    monkeypatch.setenv("BEDROCK_FALLBACK_MODEL_IDS", "")
    assert llm.get_fallback_llms() == []
    monkeypatch.setenv("BEDROCK_FALLBACK_MODEL_IDS", "us.anthropic.claude-haiku-4-5-20251001-v1:0, other-model")
    assert [m.model_id for m in llm.get_fallback_llms()] == ["us.anthropic.claude-haiku-4-5-20251001-v1:0", "other-model"]


def test_llm_runs_in_us_west_2_by_default_and_the_region_can_be_overridden(monkeypatch):
    import src.llm as llm

    monkeypatch.delenv("BEDROCK_LLM_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")  # 임베딩용 지역은 언어 모델에 영향을 주지 않는다
    assert llm.llm_region() == "us-west-2"
    assert llm.get_llm().region_name == "us-west-2" and all(m.region_name == "us-west-2" for m in llm.get_fallback_llms())
    monkeypatch.setenv("BEDROCK_LLM_REGION", "eu-west-1")
    assert llm.get_llm().region_name == "eu-west-1"
