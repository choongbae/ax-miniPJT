"""트레이싱 (T28). LangSmith에 한 번의 요청이 호출 순서대로 하나의 트리로 보이게 한다.

.env의 LANGSMITH_TRACING=true와 LANGSMITH_API_KEY가 있을 때만 켜지고, 없으면 아무 일도 하지 않는다(트레이스 실패가 서비스를 막지 않는다).
외부 서비스로 나가는 값은 줄인다: 사용자 ID는 해시한 짧은 값으로만 보내고, 저장소·검색기 같은 객체와 전체 사용자 목록은 보내지 않는다.
각 함수가 받은 인자 중 keep에 적은 것만 입력으로 남긴다.
"""
import hashlib
import os

from dotenv import load_dotenv
from langsmith import traceable

load_dotenv()
# 수업 실습(day4)과 섞이지 않게 이 프로젝트 이름으로 모은다. 바꾸려면 .env에 TRACE_PROJECT를 쓴다.
if os.getenv("LANGSMITH_TRACING", "").lower() == "true":
    os.environ["LANGSMITH_PROJECT"] = os.getenv("TRACE_PROJECT", "basketball-practice-agent")


def anonymize(user_id: str) -> str:
    return "user-" + hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:8]


def traced(name: str, run_type: str = "tool", keep: tuple[str, ...] = ()):
    """함수 호출을 트레이스에 남기는 데코레이터. keep에 없는 인자는 입력에서 뺀다(user_id는 해시로 바꿔 넣는다)."""

    def process_inputs(inputs: dict) -> dict:
        kept = {k: v for k, v in inputs.items() if k in keep}
        if "user_id" in inputs:
            kept["user"] = anonymize(inputs["user_id"])
        return kept

    def decorate(fn):
        return traceable(name=name, run_type=run_type, process_inputs=process_inputs)(fn)

    return decorate
