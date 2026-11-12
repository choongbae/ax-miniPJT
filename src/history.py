"""농구 역사 이야기 도구 (T19).

정확한 내용만 보여주기 위해 모델이 이야기를 쓰지 않는다. 검색으로 사실을 확인해 정리한 이야기(data/history.json)만 쓴다.
- 이야기마다 확인한 출처 주소와 확인한 날짜가 있다.
- 요청에 이야기와 겹치는 말(예: 올림픽, 여자, 드리블)이 있으면 그 이야기를 먼저 고르고, 없으면 무작위로 고른다.
- 정확한 기록·수치·순위를 묻는 요청은 지어내지 않고 거절하며, 널리 알려진 이야기 1건만 준다.
"""
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from src.tracing import traced

STORIES_PATH = Path(__file__).resolve().parent.parent / "data" / "history.json"
DECLINE_MESSAGE = (
    "정확한 기록이나 수치, 순위는 확실하지 않아 알려드리기 어려워요. "
    "대신 확인된 농구 이야기를 들려드릴게요."
)

# 정확한 기록·통계를 묻는 말
_RECORD_REQUEST = re.compile(r"평균|정확한|몇\s*점|몇\s*개|몇\s*승|몇\s*번|승률|득점|기록|순위|우승\s*횟수|통산")
_RECENT_WORDS = re.compile(r"최근|올해|이번 시즌|오늘|지난해|요즘|현재")


@dataclass(frozen=True)
class Story:
    id: str
    title: str
    text: str
    keywords: tuple[str, ...]
    sources: tuple[str, ...]  # 사실을 확인한 자료 주소
    checked: str  # 확인한 날짜


@dataclass(frozen=True)
class HistoryResult:
    stories: list[str]
    message: str  # 거절·안내 문구. 없으면 빈 문자열
    declined: bool  # 기록·수치 질문이라 거절했으면 True
    sources: list[str]  # 고른 이야기들의 출처 주소
    ids: list[str]


def load_stories(path: Path = STORIES_PATH) -> list[Story]:
    return [
        Story(
            id=item["id"],
            title=item["title"],
            text=item["story"],
            keywords=tuple(item.get("keywords", [])),
            sources=tuple(item["sources"]),
            checked=item["checked"],
        )
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]


def asks_for_specific_record(request: str | None) -> bool:
    """정확한 기록·수치·순위를 묻는 요청인지."""
    return bool(request and _RECORD_REQUEST.search(request))


def check_story(text: str) -> list[str]:
    """이야기 문장의 기본 형식을 확인한다(2~3문장, 최신 소식처럼 읽히는 표현 없음). 사실 확인은 출처로 한다."""
    problems: list[str] = []
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]
    if not 2 <= len(sentences) <= 3:
        problems.append(f"문장이 {len(sentences)}개입니다. 2~3문장이어야 합니다.")
    if _RECENT_WORDS.search(text):
        problems.append("최신 소식처럼 읽히는 표현은 쓸 수 없습니다. 과거의 이야기만 씁니다.")
    return problems


def _score(story: Story, request: str | None) -> int:
    if not request:
        return 0
    return sum(1 for k in story.keywords if k in request) + (1 if story.title in request else 0)


def _pick(stories: list[Story], request: str | None, n: int, rng: random.Random) -> list[Story]:
    """요청과 겹치는 말이 많은 이야기를 먼저 고르고, 나머지는 무작위로 채운다."""
    shuffled = stories[:]
    rng.shuffle(shuffled)  # 점수가 같으면 무작위 순서가 되도록 먼저 섞는다
    ranked = sorted(shuffled, key=lambda s: -_score(s, request))
    return ranked[:n]


@traced("basketball_history", keep=("request", "n"))
def basketball_history(
    request: str | None = None,
    n: int = 1,
    rng: random.Random | None = None,
) -> HistoryResult:
    """농구 역사 이야기를 n건(1~2) 돌려준다. 확인된 이야기만 쓴다.

    정확한 기록·수치를 묻는 요청이면 거절하고 이야기 1건만 준다.
    """
    rng = rng or random.Random()
    stories = load_stories()

    if asks_for_specific_record(request):
        chosen = _pick(stories, None, 1, rng)
        return HistoryResult([s.text for s in chosen], DECLINE_MESSAGE, True, _sources(chosen), [s.id for s in chosen])

    n = max(1, min(n, 2))
    chosen = _pick(stories, request, n, rng)
    return HistoryResult([s.text for s in chosen], "", False, _sources(chosen), [s.id for s in chosen])


def _sources(chosen: list[Story]) -> list[str]:
    return list(dict.fromkeys(url for s in chosen for url in s.sources))
