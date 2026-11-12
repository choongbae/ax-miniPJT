"""입력 가드레일(T21)과 출력 점검(T22).

규칙은 모두 코드로 한다(정규식과 문자열 비교). 모델을 부르지 않으므로 모델이 막혀도 동작하고 결과가 늘 같다.
- 입력: 시스템 프롬프트 요구·지시 무시, 다른 사용자 정보, 영상·개인 자세 분석, 의료 진단·치료, 난이도 강제 변경.
- 출력: 답변에 시스템 프롬프트, 다른 사용자의 정보, 비밀 값(키 등)이 섞이지 않았는지 확인.
"""
import os
import re
from dataclasses import dataclass

from src.tools import judge_shot_difficulty
from src.tracing import traced

# 카테고리 -> 사용자에게 보여 줄 안내. 어느 경우에도 정중하게 거절하고 할 수 있는 일을 알려 준다.
MESSAGES = {
    "prompt_injection": "시스템 설정이나 내부 지시는 알려드릴 수 없어요. 대신 연습 계획, 연습 기록, 농구 지식에 대해서는 도와드릴 수 있어요.",
    "other_user": "다른 사용자의 기록이나 정보는 보여드릴 수 없어요. 본인의 연습 기록과 계획만 확인할 수 있어요.",
    "video_analysis": "영상이나 개인 자세·폼 분석은 지원하지 않아요. 연습한 뒤 직접 기록을 입력해 주시면 다음 계획에 반영해 드려요.",
    "medical": "부상이나 통증의 진단과 치료는 도와드릴 수 없어요. 통증이 계속되면 연습을 쉬고 의사나 전문가와 상담해 주세요.",
    "force_difficulty": "난이도는 연습 기록으로 정해진 규칙에 따라 바뀌어서 직접 올리거나 내릴 수 없어요. 연습 기록을 알려 주시면 규칙에 맞게 다음 계획에 반영해 드려요.",
}


@dataclass(frozen=True)
class GuardResult:
    category: str
    message: str
    detail: str = ""  # trace에 남길 보충 설명 (예: 규칙으로 계산한 난이도)


# --- 입력 가드레일 -----------------------------------------------------------------

_INJECTION = [
    r"(이전|앞의|위의|기존|모든)\s*(지시|명령|규칙|프롬프트|설정)\S*\s*(를|은|는)?\s*(모두|전부|다)?\s*(무시|잊어|버려|취소)",
    r"시스템\s*프롬프트",
    r"프롬프트\S*\s*(를|을)?\s*(그대로|알려|보여|출력|공개)",
    r"(지시|명령|설정|지침)\S*\s*(를|을)?\s*(그대로\s*)?(알려|보여|출력|공개)\s*(줘|달라|주세요|봐)",
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above)",
    r"system\s*prompt",
    r"(너|당신)는\s*이제부터",
    r"개발자\s*모드|developer\s*mode|jailbreak|탈옥",
]
_OTHER_USER_WORD = re.compile(r"다른\s*(사용자|사람|회원|유저|선수)\S*")
_NAMED_RECORD = re.compile(r"([가-힣]{2,4})\s*(님|씨|선수)?\s*(의|이?\s*의)\s*(연습\s*)?(기록|계획|정보|데이터)")
_NOT_A_NAME = {
    "지난주", "이번주", "저번주", "다음주", "이번", "지난", "다음", "오늘", "어제", "내일", "올해", "작년", "전체", "모든",
    "나의", "내", "제", "저", "우리", "나", "연습", "슛", "드리블", "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일",
}
_SEE_VERB = re.compile(r"보여|알려|조회|확인|공개|줘|열어|가져")
_VIDEO = [
    r"(영상|동영상|비디오|녹화|촬영)\S*.{0,25}(분석|올릴|올려|보낼|보내|업로드|교정|고쳐|봐\s*줘)",
    r"(분석|교정)\S*.{0,10}(영상|동영상|비디오)",
    r"(내|제|저의?)\s*(슛|드리블|레이업)?\s*(자세|폼)\S*.{0,15}(분석|교정|고쳐|평가|봐\s*줘)",
]
_MEDICAL = [
    r"진단", r"처방", r"치료", r"병명", r"무슨\s*병", r"어떤\s*병", r"수술", r"약을?\s*(먹|추천|사)", r"재활\s*(방법|운동|프로그램)",
]
_FORCE = [
    r"(그냥|무조건|상관\s*없이|마음대로|내\s*맘대로|내가\s*정한).{0,12}난이도.{0,8}(올려|높여|내려|낮춰|바꿔|고쳐)",
    r"난이도\s*(를|은)?\s*(그냥|무조건|마음대로)?\s*(올려|높여|내려|낮춰)\s*(서|줘|주세요|달라|봐)",
    r"성공률\S*.{0,15}(상관\s*없이|무시하고|말고).{0,15}난이도",
]


def _matches(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text, re.I) for p in patterns)


def _asks_for_other_users_data(text: str) -> bool:
    if _OTHER_USER_WORD.search(text) and _SEE_VERB.search(text):
        return True
    for m in _NAMED_RECORD.finditer(text):
        if m.group(1) not in _NOT_A_NAME and _SEE_VERB.search(text):
            return True
    return False


@traced("guardrail_input", keep=("question",))
def check_input(question: str) -> GuardResult | None:
    """질문이 정책을 어기는지 확인한다. 어기면 거절 안내를, 괜찮으면 None을 돌려준다."""
    text = question.strip()
    if _matches(_INJECTION, text):
        return GuardResult("prompt_injection", MESSAGES["prompt_injection"])
    if _asks_for_other_users_data(text):
        return GuardResult("other_user", MESSAGES["other_user"])
    if _matches(_VIDEO, text):
        return GuardResult("video_analysis", MESSAGES["video_analysis"])
    if _matches(_MEDICAL, text):
        return GuardResult("medical", MESSAGES["medical"])
    if _matches(_FORCE, text):
        return _force_difficulty(text)
    return None


def _force_difficulty(text: str) -> GuardResult:
    """난이도 강제 요청: 성공률이 함께 있으면 규칙으로 계산한 결과를 알려 준다."""
    message = MESSAGES["force_difficulty"]
    detail = ""
    m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
    if m and 0 <= float(m.group(1)) <= 100:
        rate = float(m.group(1))
        j = judge_shot_difficulty(100, round(rate))  # 시도 횟수를 말하지 않아 100회로 가정
        detail = f"성공률 {rate:g}% (시도 100회로 가정) -> {j.verdict}"
        message = f"성공률 {rate:g}%라면 규칙에 따라 다음 주 난이도는 '{j.verdict}'이에요. " + message
    return GuardResult("force_difficulty", message, detail)


# --- 출력 점검 --------------------------------------------------------------------

LEAK_MESSAGE = "안전을 위해 이 답변은 보여드릴 수 없어요. 연습 계획, 연습 기록, 농구 지식에 대해 다시 물어봐 주세요."
_WINDOW = 25  # 시스템 프롬프트와 이만큼 이어서 같은 글자가 나오면 노출로 본다
_SECRET_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSWORD", re.I)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _leaks_prompt(answer: str, prompts: list[str]) -> bool:
    flat = _normalize(answer)
    for prompt in prompts:
        p = _normalize(prompt)
        for i in range(0, max(len(p) - _WINDOW, 0) + 1, 5):
            if p[i : i + _WINDOW] and p[i : i + _WINDOW] in flat:
                return True
    return False


@traced("guardrail_output", keep=("answer",))
def check_output(
    answer: str,
    user_id: str,
    known_user_ids: list[str] | None = None,
    prompts: list[str] | None = None,
    env: dict | None = None,
) -> str | None:
    """답변에 시스템 프롬프트, 다른 사용자의 정보, 비밀 값이 섞였는지 확인한다. 문제가 없으면 None, 있으면 이유를 돌려준다."""
    if prompts and _leaks_prompt(answer, prompts):
        return "시스템 프롬프트 노출"
    for other in known_user_ids or []:
        if other != user_id and len(other) >= 2 and other in answer:
            return f"다른 사용자({other}) 정보 노출"
    for name, value in (os.environ if env is None else env).items():
        if _SECRET_NAME.search(name) and value and len(value) >= 12 and value in answer:
            return f"비밀 값({name}) 노출"
    return None
