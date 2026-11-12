import random
import re

import src.history as history
from src.agent import format_result, run_agent
from src.history import (
    DECLINE_MESSAGE,
    asks_for_specific_record,
    basketball_history,
    check_story,
    load_stories,
)
from src.models import UserInput, WeeklyPlan
from src.tools import load_drills

STORIES = load_stories()
BY_ID = {s.id: s for s in STORIES}


# --- 이야기 데이터: 정확성을 지키는 구조 --------------------------------------------

def test_there_are_about_a_dozen_stories_with_unique_ids():
    assert len(STORIES) >= 12
    assert len({s.id for s in STORIES}) == len(STORIES)


def test_every_story_has_checked_sources_and_a_check_date():
    for s in STORIES:
        assert len(s.sources) >= 2, f"{s.id}: 출처가 2개 미만"
        assert all(re.match(r"https://\S+$", url) for url in s.sources), s.id
        assert re.match(r"\d{4}-\d{2}-\d{2}$", s.checked), s.id


def test_sources_are_unique_per_story_and_not_placeholders():
    for s in STORIES:
        assert len(set(s.sources)) == len(s.sources), s.id
        assert not any("example.com" in url for url in s.sources), s.id


def test_every_story_passes_the_basic_format_check():
    for s in STORIES:
        assert check_story(s.text) == [], (s.id, check_story(s.text))


def test_stories_have_no_quotes_or_invented_dialogue():
    for s in STORIES:
        assert not re.search(r"[\"“”‘’'「」『』]", s.text), s.id


def test_stories_hedge_claims_that_sources_disagree_on():
    # 자료마다 달라서 단정하지 않기로 한 이야기는 '알려져 있습니다/전해집니다'를 쓴다
    for story_id in ("backboard", "orange-ball", "shot-clock", "first-game", "womens-first-game", "olympic-sport", "origin-of-dribble"):
        assert re.search(r"알려져 있|전해집니다|합니다\.$", BY_ID[story_id].text), story_id


def test_contested_details_are_left_out():
    text = {s.id: s.text for s in STORIES}
    assert not re.search(r"\d{4}", text["backboard"])  # 백보드 연도는 자료마다 달라서 쓰지 않는다
    assert "바이어손" not in text["shot-clock"] and "페리스" not in text["shot-clock"]  # 24초 창안자는 자료마다 다르다


def test_korean_introduction_story_is_not_included_because_sources_conflict():
    assert not any("YMCA" in s.text or "질레트" in s.text for s in STORIES)


def test_each_story_title_and_keywords_exist():
    for s in STORIES:
        assert s.title and s.keywords, s.id


# --- 기록·수치 질문은 거절 (케이스 11) -----------------------------------------------

def test_case11_specific_record_question_is_detected():
    assert asks_for_specific_record("1998년 KBL 정규리그에서 한 팀의 정확한 시즌 평균 득점이 몇 점이었어?")
    assert asks_for_specific_record("NBA에서 가장 많은 득점을 한 선수가 누구야?")
    assert not asks_for_specific_record("농구 역사에서 재미있는 이야기 하나 알려줘.")
    assert not asks_for_specific_record(None)


def test_case11_is_declined_and_gets_one_verified_story():
    out = basketball_history("1998년 KBL 정규리그에서 한 팀의 정확한 시즌 평균 득점이 몇 점이었어?")
    assert out.declined is True and out.message == DECLINE_MESSAGE
    assert len(out.stories) == 1 and out.stories[0] in {s.text for s in STORIES}
    assert out.sources  # 대신 보여 주는 이야기에도 출처가 있다
    assert not any(ch.isdigit() for ch in out.message)  # 거절 문구에 지어낸 수치가 없다


# --- 이야기 고르기 -------------------------------------------------------------------

def test_case8_generic_request_returns_a_verified_story_with_sources():
    out = basketball_history("농구 역사에서 재미있는 이야기 하나 알려줘.")
    assert out.declined is False and out.message == ""
    assert len(out.stories) == 1 and out.stories[0] in {s.text for s in STORIES}
    assert out.ids and out.sources


def test_story_matching_the_request_is_chosen():
    assert basketball_history("올림픽 이야기 해줘", rng=random.Random(1)).ids[0] in {"olympic-sport", "dream-team", "womens-olympics"}
    assert basketball_history("여자 농구는 언제 시작했어?", rng=random.Random(2)).ids[0] in {"womens-first-game", "womens-olympics"}
    assert basketball_history("백보드는 왜 생겼어?").ids == ["backboard"]
    assert basketball_history("24초 룰 이야기").ids == ["shot-clock"]
    assert basketball_history("KBL은 언제 생겼어?").ids == ["kbl-start"]


def test_generic_request_gives_variety_across_random_seeds():
    seen = {basketball_history("재미있는 이야기", rng=random.Random(seed)).ids[0] for seed in range(30)}
    assert len(seen) >= 6


def test_same_seed_gives_same_story():
    assert basketball_history(rng=random.Random(7)).ids == basketball_history(rng=random.Random(7)).ids


def test_requested_count_is_between_one_and_two_without_repeats():
    assert len(basketball_history(n=5).stories) == 2
    assert len(basketball_history(n=0).stories) == 1
    two = basketball_history(n=2, rng=random.Random(3))
    assert len(set(two.ids)) == 2


def test_sources_are_the_union_of_the_chosen_stories_sources():
    out = basketball_history("올림픽", n=2, rng=random.Random(4))
    expected = []
    for story_id in out.ids:
        expected += list(BY_ID[story_id].sources)
    assert out.sources == list(dict.fromkeys(expected))


# --- 모델을 전혀 부르지 않는다 -------------------------------------------------------

def test_history_module_has_no_model_code():
    assert not hasattr(history, "get_llm") and not hasattr(history, "_generate")
    source = open(history.__file__, encoding="utf-8").read()
    assert "langchain" not in source and "src.llm" not in source


# --- 계획 화면 -----------------------------------------------------------------------

def _plan():
    return WeeklyPlan.model_validate(
        {"days": [{"day": "월", "drills": [{"name": "제자리 볼 핸들링", "sets": 3, "reps": 10, "minutes": 30, "purpose": "p"}]}]}
    )


def test_plan_screen_shows_one_verified_story():
    user = UserInput(position="가드", level="초급", goals=[], days_per_week=3, minutes_per_session=40, equipment=[])
    state = run_agent(user, load_drills(), generate_fn=lambda *a, **k: _plan())
    assert len(state["history"]) == 1 and state["history"][0] in {s.text for s in STORIES}
    text = format_result(state)
    assert "[오늘의 농구 이야기]" in text and state["history"][0] in text


def test_failed_plan_has_no_story():
    bad = WeeklyPlan.model_validate(
        {"days": [{"day": "월", "drills": [{"name": "3점 캐치앤슛", "sets": 3, "reps": 10, "minutes": 30, "purpose": "p"}]}]}
    )
    user = UserInput(position="가드", level="초급", goals=[], days_per_week=3, minutes_per_session=40, equipment=[])
    state = run_agent(user, load_drills(), generate_fn=lambda *a, **k: bad)  # 골대가 없는데 슛 -> 계속 위반
    assert state["status"] == "failed" and state["history"] == []
    assert "[오늘의 농구 이야기]" not in format_result(state)
