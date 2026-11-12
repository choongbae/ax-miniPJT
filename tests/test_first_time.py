from src.agent import collect_input, main
from src.models import UserInput, WeeklyPlan
from src.records import RecordStore

PLAN = WeeklyPlan.model_validate(
    {"days": [{"day": "월", "drills": [{"name": "제자리 볼 핸들링", "sets": 3, "reps": 10, "minutes": 30, "purpose": "p"}]}]}
)


def feeder(answers):
    asked = []
    it = iter(answers)

    def ask(prompt):
        asked.append(prompt)
        return next(it)

    ask.asked = asked
    return ask


def ok_run(user):
    return {"user": user, "plan": PLAN, "status": "ok", "violations": [], "notices": []}


def test_case26_first_time_user_is_asked_and_beginner_skips_level_and_position():
    ask = feeder(["예", "", "3", "30", "골대, 콘"])  # 초보자 -> 포지션·수준 질문 없음
    raw = collect_input(ask, first_time=True)
    assert ask.asked[0].startswith("농구를 처음 시작하는 사람인가요?")
    assert not any("포지션" in p or "실력 수준" in p for p in ask.asked)
    assert raw["is_beginner"] is True and "level" not in raw


def test_first_time_user_answering_no_gets_normal_questions():
    ask = feeder(["아니오", "가드", "중급", "3점슛", "3", "40", "골대"])
    raw = collect_input(ask, first_time=True)
    assert raw["is_beginner"] is False
    assert raw["position"] == "가드" and raw["level"] == "중급"
    assert any("실력 수준" in p for p in ask.asked)


def test_user_with_records_is_not_asked_case28(tmp_path):
    store = RecordStore(tmp_path / "r.json")
    store.add_shot("me", "3점 캐치앤슛", "2026-W45", 50, 20)
    ask = feeder(["가드", "중급", "3점슛", "3", "40", "골대, 콘"])
    got = {}

    def run(user):
        got["user"] = user
        return ok_run(user)

    code = main(input_fn=ask, run=run, out=lambda *_: None, store=store, user_id="me")
    assert code == 0
    assert not any("처음 시작하는 사람" in p for p in ask.asked)  # 기록이 있으면 묻지 않는다
    assert got["user"].is_beginner is False and got["user"].level == "중급"


def test_user_without_records_is_asked_in_main(tmp_path):
    store = RecordStore(tmp_path / "r.json")
    ask = feeder(["예", "", "3", "30", "골대, 콘"])
    got = {}

    def run(user):
        got["user"] = user
        return ok_run(user)

    code = main(input_fn=ask, run=run, out=lambda *_: None, store=store, user_id="new")
    assert code == 0
    assert any("처음 시작하는 사람" in p for p in ask.asked)
    user: UserInput = got["user"]
    assert user.is_beginner and user.level == "초급" and user.position == "미정"


def test_another_users_records_do_not_count(tmp_path):
    store = RecordStore(tmp_path / "r.json")
    store.add_shot("someone_else", "3점 캐치앤슛", "2026-W45", 50, 20)
    ask = feeder(["아니오", "가드", "중급", "", "3", "40", ""])
    main(input_fn=ask, run=ok_run, out=lambda *_: None, store=store, user_id="me")
    assert any("처음 시작하는 사람" in p for p in ask.asked)


def test_main_without_store_never_asks_beginner_question():
    ask = feeder(["가드", "중급", "", "3", "40", ""])
    main(input_fn=ask, run=ok_run, out=lambda *_: None)
    assert not any("처음 시작하는 사람" in p for p in ask.asked)
