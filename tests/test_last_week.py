"""T24: 지난주 계획과 기록이 다음 주 계획에 자동으로 반영되는지 확인한다."""
from datetime import date

import pytest

from src.models import WeeklyPlan
from src.orchestrator import ParsedRequest, answer_question
from src.records import RecordStore, next_week_key
from src.store import SqliteStore
from src.tools import load_drills

CATALOG = load_drills()
WEEK1 = date(2026, 11, 10)  # 2026-W46
WEEK2 = date(2026, 11, 17)  # 2026-W47
PARSED = ParsedRequest(
    intent="plan", position="가드", level="중급", goals=["3점슛"], days_per_week=3, minutes_per_session=40, equipment=["골대", "콘"]
)


def plan_of(*names):
    drills = [{"name": n, "sets": 3, "reps": 10, "minutes": 10, "purpose": "p"} for n in names]
    return WeeklyPlan.model_validate({"days": [{"day": "월", "drills": drills}]})


class Gen:
    """계획 생성 대신 쓰는 가짜. 받은 판정과 위반 사유를 기록한다."""

    def __init__(self, *plans):
        self.plans, self.judgments, self.violations = list(plans), [], []

    def __call__(self, user, catalog, violations, judgments=None, menus=None):
        self.violations.append(violations)
        self.judgments.append(judgments)
        return self.plans[min(len(self.violations) - 1, len(self.plans) - 1)]


@pytest.fixture(params=["json", "sqlite"])
def store(request, tmp_path):
    """T24의 모든 동작은 JSON 저장소와 SQLite 저장소 양쪽에서 같아야 한다."""
    return RecordStore(tmp_path / "records.json") if request.param == "json" else SqliteStore(tmp_path / "app.db")


def ask(store, today, gen, user_id="me", parsed=PARSED):
    return answer_question("계획 짜줘", store=store, catalog=CATALOG, user_id=user_id, parse_fn=lambda q: parsed, generate_fn=gen, today=today)


def steps(resp):
    return [t["step"] for t in resp.trace]


def test_week_arithmetic_crosses_year_boundary():
    assert next_week_key("2026-W46") == "2026-W47"
    assert next_week_key("2026-W53") == "2027-W01"


def test_generated_plan_is_saved_for_the_week(store):
    ask(store, WEEK1, Gen(plan_of("3점 캐치앤슛", "풀업 점퍼")))
    saved = store.get_plan("me", "2026-W46")
    assert [d.name for d in saved.days[0].drills] == ["3점 캐치앤슛", "풀업 점퍼"]


def test_plan_survives_reload_and_same_week_is_replaced(store, tmp_path):
    ask(store, WEEK1, Gen(plan_of("3점 캐치앤슛")))
    ask(store, WEEK1, Gen(plan_of("풀업 점퍼")))
    reloaded = type(store)(store.path)  # 같은 파일을 다시 연다
    assert [d.name for d in reloaded.get_plan("me", "2026-W46").days[0].drills] == ["풀업 점퍼"]
    if hasattr(reloaded, "_entries"):
        assert sum(1 for e in reloaded._entries if "plan" in e) == 1  # 같은 주 계획은 하나만


def test_no_previous_plan_means_no_judgments(store):
    gen = Gen(plan_of("3점 캐치앤슛"))
    resp = ask(store, WEEK2, gen)
    assert "judge_difficulty" not in steps(resp) and gen.judgments == [None]
    assert "[지난주 결과]" not in resp.answer


def test_last_weeks_records_are_applied_automatically_case3(store):
    ask(store, WEEK1, Gen(plan_of("3점 캐치앤슛", "양손 레이업")))  # 지난주에 받은 계획
    store.add_shot("me", "3점 캐치앤슛", "2026-W46", 50, 10)  # 지난주 기록: 20% -> 하향
    store.add_rating("me", "양손 레이업", "2026-W46", "쉬웠음")  # 지난주 기록: 쉬웠음 -> 상향

    gen = Gen(plan_of("미드레인지 제자리 점프슛", "제자리 자유투", "컷 후 무빙슛", "스텝백 점퍼"))
    resp = ask(store, WEEK2, gen)

    by_drill = {j.drill: j for j in gen.judgments[0]}
    assert by_drill["3점 캐치앤슛"].verdict == "하향" and by_drill["양손 레이업"].verdict == "상향"
    assert steps(resp)[:4] == ["parse_question", "validate_input", "judge_difficulty", "judge_difficulty"]
    assert "[지난주 결과]" in resp.answer and "3점 캐치앤슛: 난이도 하향" in resp.answer


def test_plan_that_ignores_last_weeks_result_is_regenerated(store):
    ask(store, WEEK1, Gen(plan_of("3점 캐치앤슛")))
    store.add_shot("me", "3점 캐치앤슛", "2026-W46", 50, 10)
    gen = Gen(plan_of("3점 캐치앤슛"), plan_of("미드레인지 제자리 점프슛"))  # 처음 계획은 하향을 무시
    resp = ask(store, WEEK2, gen)
    assert len(gen.violations) == 2 and any("그대로 넣으면 안 됩니다" in v for v in gen.violations[1])
    assert "미드레인지 제자리 점프슛" in resp.answer


def test_menu_without_last_weeks_record_is_put_back_case10(store):
    ask(store, WEEK1, Gen(plan_of("양손 레이업", "제자리 볼 핸들링")))
    store.add_rating("me", "제자리 볼 핸들링", "2026-W46", "적당")  # 레이업은 기록 없음
    gen = Gen(plan_of("제자리 볼 핸들링"), plan_of("양손 레이업", "제자리 볼 핸들링"))
    resp = ask(store, WEEK2, gen)
    assert any("다시 넣어야 합니다" in v for v in gen.violations[1])
    assert "양손 레이업: 난이도 유지" in resp.answer and "다시 넣습니다" in resp.answer


def test_a_user_only_sees_their_own_last_week(store):
    ask(store, WEEK1, Gen(plan_of("3점 캐치앤슛")), user_id="other")
    store.add_shot("other", "3점 캐치앤슛", "2026-W46", 50, 10)
    gen = Gen(plan_of("3점 캐치앤슛"))
    resp = ask(store, WEEK2, gen, user_id="me")
    assert gen.judgments == [None] and "judge_difficulty" not in steps(resp)


def test_older_weeks_are_not_used_as_last_week(store):
    ask(store, date(2026, 11, 3), Gen(plan_of("3점 캐치앤슛")))  # W45 계획
    store.add_shot("me", "3점 캐치앤슛", "2026-W45", 50, 10)
    gen = Gen(plan_of("3점 캐치앤슛"))
    ask(store, WEEK2, gen)  # W47의 지난주는 W46이다
    assert gen.judgments == [None]


def test_failed_plan_is_not_saved(store):
    bad = plan_of("벽 패스")  # 벽이 없다고 했는데 벽 패스 -> 계속 위반
    resp = ask(store, WEEK1, Gen(bad))
    assert "만들지 못했습니다" in resp.answer
    assert store.get_plan("me", "2026-W46") is None


def test_record_with_next_plan_saves_the_plan_for_next_week(store):
    parsed = ParsedRequest(intent="record", wants_next_plan=True, reports=[
        {"drill": "3점슛", "shot_sessions": [{"attempts": 50, "makes": 10}]}
    ])
    answer_question("3점슛 50회 중 10회 넣었어. 다음 주 계획 짜줘", store=store, catalog=CATALOG, user_id="me",
                    parse_fn=lambda q: parsed, generate_fn=Gen(plan_of("미드레인지 제자리 점프슛")), today=WEEK1)
    assert store.get_plan("me", "2026-W47") is not None and store.get_plan("me", "2026-W46") is None


def test_full_two_week_flow_through_the_agent(store):
    """1주차 계획 -> 기록 -> 2주차 계획에 자동 반영까지 에이전트 안에서 이어진다."""
    ask(store, WEEK1, Gen(plan_of("3점 캐치앤슛", "제자리 볼 핸들링")))
    record = ParsedRequest(intent="record", reports=[
        {"drill": "3점슛", "shot_sessions": [{"attempts": 50, "makes": 30}]},  # 60% -> 상향
        {"drill": "제자리 볼 핸들링", "ratings": ["적당", "적당"]},  # 유지
    ])
    answer_question("기록", store=store, catalog=CATALOG, user_id="me", parse_fn=lambda q: record, today=WEEK1)

    gen = Gen(plan_of("컷 후 무빙슛", "제자리 볼 핸들링"))
    resp = ask(store, WEEK2, gen)
    verdicts = {j.drill: j.verdict for j in gen.judgments[0]}
    assert verdicts == {"3점 캐치앤슛": "상향", "제자리 볼 핸들링": "유지"}
    assert "컷 후 무빙슛" in resp.answer


def test_plan_entries_do_not_break_record_lookups(store):
    """계획 항목에는 연습 메뉴 이름이 없어서, 기록 조회가 이를 건너뛰어야 한다 (예전에는 KeyError가 났다)."""
    store.save_plan("me", "2026-W46", plan_of("3점 캐치앤슛"))
    assert store.shots("me", "3점 캐치앤슛", "2026-W46") == []
    assert store.ratings("me", "3점 캐치앤슛", "2026-W46") == []
    assert store.past_weeks("me", "3점 캐치앤슛", "2026-W47") == []
    assert store.has_records("me") and store.user_ids() == ["me"]
