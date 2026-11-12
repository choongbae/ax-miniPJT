"""Bedrock LLM 생성. 키와 리전은 .env에서 읽는다 (코드에 키를 쓰지 않는다)."""
import os

from botocore.config import Config
from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse

load_dotenv()

# CLAUDE.md의 기본 모델(claude-3-5-sonnet-20241022-v2)은 서비스가 종료되었다.
# 사용자가 지정한 모델을 기본으로 쓴다. 필요하면 .env의 BEDROCK_MODEL_ID로 바꾼다.
DEFAULT_MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"


# 기본 모델이 한도 초과·권한 오류·종료 등으로 실패하면 차례로 시도하는 대체 모델(이 계정에서 호출이 확인된 모델).
# 필요하면 .env의 BEDROCK_FALLBACK_MODEL_IDS에 쉼표로 구분해 바꾼다. 빈 값이면 대체 없이 실패한다.
DEFAULT_FALLBACK_MODEL_IDS = ["global.anthropic.claude-haiku-4-5-20251001-v1:0"]


# 기본 모델이 한도 초과(Throttling)일 때 boto3 기본값(최대 4번 재시도)을 그대로 두면 호출마다 7초 넘게 기다린 뒤에야
# 대체 모델로 넘어간다. 재시도를 한 번만 하고 바로 대체 모델로 넘어가게 한다.
FAST_FAIL = Config(retries={"max_attempts": 1, "mode": "standard"})


# 언어 모델은 us-west-2에서 부른다. 임베딩(src/retriever.py)은 .env의 AWS_DEFAULT_REGION을 그대로 쓴다.
# 바꾸려면 .env의 BEDROCK_LLM_REGION을 쓴다.
DEFAULT_LLM_REGION = "us-west-2"


def llm_region() -> str:
    return os.getenv("BEDROCK_LLM_REGION") or DEFAULT_LLM_REGION


def _fallback_ids() -> list[str]:
    raw = os.getenv("BEDROCK_FALLBACK_MODEL_IDS")
    return DEFAULT_FALLBACK_MODEL_IDS if raw is None else [m.strip() for m in raw.split(",") if m.strip()]


def get_llm(temperature: float = 0.0) -> ChatBedrockConverse:
    return ChatBedrockConverse(
        model=os.getenv("BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
        region_name=llm_region(),
        temperature=temperature,
        config=FAST_FAIL if _fallback_ids() else None,  # 대체 모델이 있을 때만 빨리 포기한다
    )


def get_fallback_llms(temperature: float = 0.0) -> list[ChatBedrockConverse]:
    region = llm_region()
    return [ChatBedrockConverse(model=m, region_name=region, temperature=temperature) for m in _fallback_ids()]


def get_llm_with_fallbacks(temperature: float = 0.0):
    """기본 모델이 실패하면 대체 모델로 이어서 시도하는 모델 (구조화 출력이 필요 없는 일반 호출용)."""
    primary = get_llm(temperature)
    fallbacks = get_fallback_llms(temperature)
    return primary.with_fallbacks(fallbacks) if fallbacks else primary


def structured_chain(template, schema, llm=None):
    """프롬프트 템플릿과 구조화 출력(schema)을 잇는 체인. llm을 주면 그것만, 아니면 기본 모델과 대체 모델을 이어서 쓴다."""
    if llm is not None:
        return template | llm.with_structured_output(schema)
    chain = template | get_llm().with_structured_output(schema)
    fallbacks = [template | m.with_structured_output(schema) for m in get_fallback_llms()]
    return chain.with_fallbacks(fallbacks) if fallbacks else chain


if __name__ == "__main__":
    # 첫 호출 확인용: python -m src.llm
    print(get_llm().invoke("농구 슛 연습의 핵심을 한 문장으로 말해줘.").content)
