"""가장 어려운 메뉴에서 상향이 나올 때 (T39): 그 메뉴는 유지하고, 규칙으로 고른 다른 분야 메뉴를 추천한다."""
import pytest
from fastapi.testclient import TestClient

from src.adjust import format_judgments, validate_adjustments
from src.models import UserInput, WeeklyPlan
from src.progress import field_of
from src.recommend import field_record_counts, is_at_top, recommend_other_fields
from src.tools import DrillJudgment, load_drills
from tests.test_web import FORM, env, make_plan, plan_with, signup, user  # noqa: F401

CATALOG = load_drills()
BY = {d.name: d for d in CATALOG}
ALL = ["골대", "콘", "벽"]


def user_with(equipment, goals=(), level="상급", beginner=False):
    return UserInput(position="미정", level="초급" if beginner else level, is_beginner=beginner, goals=list(goals),
                     days_per_week=3, minutes_per_session=40, equipment=equipment)


def raised(name):
    return DrillJudgment(name, "상향", "x")


def zero_counts():
    return {"슛": 0, "드리블": 0, "레이업": 0, "패스": 0, "기타": 0}


# --- 올릴 곳이 있는가 ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,equipment,expected", [
    ("스텝백 점퍼", ALL, True),  # 상급 슛: 더 어려운 슛이 없다
    ("고개 든 드리블", [], True),  # 상급 슛 외
    ("3점 캐치앤슛", ALL, False),  # 중급 슛: 상급 슛이 있다
    ("제자리 볼 핸들링", [], False),  # 초급 드리블: 더 어려운 슛 외 메뉴가 있다
    ("3점 캐치앤슛", ["골대"], False),  # 골대만으로도 스텝백 점퍼(상급)를 할 수 있다
    ("풀업 점퍼", ["골대"], False),
    ("제자리 자유투", [], True),  # 장비가 없으면 올라갈 슛 메뉴도 할 수 없으니 올릴 곳이 없다 (이 메뉴 자체도 계획에 못 들어가는 경우)
])
def test_is_at_top(name, equipment, expected):
    assert is_at_top(raised(name), BY[name], CATALOG, user_with(equipment)) is expected


def test_only_raises_without_carry_over_count():
    top = BY["고개 든 드리블"]
    assert not is_at_top(DrillJudgment(top.name, "유지", "x"), top, CATALOG, user_with([]))
    assert not is_at_top(DrillJudgment(top.name, "하향", "x"), top, CATALOG, user_with([]))
    assert not is_at_top(DrillJudgment(top.name, "유지", "x", carry_over=True), top, CATALOG, user_with([]))


# --- 추천 규칙 --------------------------------------------------------------------------------

def test_recommends_a_menu_of_another_field_usable_with_the_users_equipment():
    recs = recommend_other_fields([raised("고개 든 드리블")], CATALOG, user_with(["벽"]), zero_counts(), set())
    assert len(recs) == 1
    r = recs[0]
    menu = BY[r.menu]
    assert r.kept == "고개 든 드리블" and r.field != "드리블" and set(menu.requires) <= {"벽"} and r.field == "슛"  # 기록이 같으면 슛 먼저
    assert r.menu == "한 손 슛 폼 연습"  # 장비 없이 되는 슛 분야 메뉴 중 가장 어려운(중급) 것
    assert "고개 든 드리블" in r.text and "이미 가장 어려운 난이도" in r.text and r.menu in r.text and "그대로 유지" in r.text


def test_the_field_with_the_fewest_records_comes_first_then_the_hardest_menu():
    counts = {"슛": 9, "드리블": 9, "레이업": 5, "패스": 0, "기타": 3}
    r = recommend_other_fields([raised("고개 든 드리블")], CATALOG, user_with(ALL), counts, set())[0]
    assert r.field == "패스" and r.menu == "벽 한 손 패스 연속" and r.difficulty == "상급"  # 기록 0건인 패스, 그중 가장 어려운 메뉴
    assert "패스 기록 0건" in r.text
    counts["패스"] = 4  # 기록이 더 적은 분야가 없다면 기타(3건)
    assert recommend_other_fields([raised("고개 든 드리블")], CATALOG, user_with(ALL), counts, set())[0].field == "기타"


def test_the_same_field_is_never_recommended():
    for name in ("스텝백 점퍼", "고개 든 드리블", "벽 한 손 패스 연속", "시간 제한 레이업 연속 마무리"):
        r = recommend_other_fields([raised(name)], CATALOG, user_with(ALL), zero_counts(), set())[0]
        assert r.field != field_of(BY[name])


def test_menus_already_in_the_plan_are_not_recommended_and_two_raises_get_different_menus():
    both = [raised("고개 든 드리블"), raised("스텝백 점퍼")]
    recs = recommend_other_fields(both, CATALOG, user_with(ALL), zero_counts(), set())
    assert len(recs) == 2 and recs[0].menu != recs[1].menu
    skip = {recs[0].menu}
    again = recommend_other_fields([raised("고개 든 드리블")], CATALOG, user_with(ALL), zero_counts(), skip)
    assert again[0].menu not in skip


def test_nothing_is_recommended_when_a_raise_still_has_somewhere_to_go_or_no_other_menu_fits():
    assert recommend_other_fields([raised("3점 캐치앤슛")], CATALOG, user_with(ALL), zero_counts(), set()) == []  # 올릴 곳이 있다
    assert recommend_other_fields([], CATALOG, user_with(ALL), zero_counts(), set()) == []
    assert recommend_other_fields(None, CATALOG, user_with(ALL), zero_counts(), set()) == []
    everything = {d.name for d in CATALOG}
    assert recommend_other_fields([raised("고개 든 드리블")], CATALOG, user_with(ALL), zero_counts(), everything) == []  # 고를 메뉴가 없다


def test_recommendations_stay_within_the_beginner_level():
    r = recommend_other_fields([raised("고개 든 드리블")], CATALOG, user_with(ALL, beginner=True), zero_counts(), set())[0]
    assert r.difficulty == "초급"


# --- 계획 생성에 주는 지시와 검증 --------------------------------------------------------------

def test_the_prompt_says_to_keep_the_top_menu_and_the_plan_must_keep_it():
    u = user_with([])
    text = format_judgments([raised("고개 든 드리블")], CATALOG, u)
    assert "고개 든 드리블" in text and "그대로 유지" in text and "세트·반복" not in text
    without = plan_with("제자리 볼 핸들링")
    kept = plan_with("고개 든 드리블")
    assert any("그대로 유지해서 넣어야" in v for v in validate_adjustments(without, [raised("고개 든 드리블")], CATALOG, u))
    assert validate_adjustments(kept, [raised("고개 든 드리블")], CATALOG, u) == []


def test_a_raise_with_somewhere_to_go_is_still_changed_as_before():
    u = user_with(ALL)
    stay = plan_with("3점 캐치앤슛")
    assert validate_adjustments(stay, [raised("3점 캐치앤슛")], CATALOG, u)  # 그대로 넣으면 위반 (기존 규칙)


def test_downward_with_nothing_easier_is_unchanged_behavior():
    d = DrillJudgment("제자리 볼 핸들링", "하향", "x")
    assert validate_adjustments(plan_with("제자리 볼 핸들링"), [d], CATALOG, user_with([])) == []


# --- 기록량 세기 --------------------------------------------------------------------------------

def test_field_record_counts_look_at_the_eight_weeks_before_the_target_week(tmp_path):
    from src.store import SqliteStore

    s = SqliteStore(tmp_path / "a.db")
    s.add_shot("u", "3점 캐치앤슛", "2026-W45", 20, 10)
    s.add_shot("u", "3점 캐치앤슛", "2026-W44", 20, 10)
    s.add_rating("u", "제자리 볼 핸들링", "2026-W40", "쉬웠음")
    s.add_rating("u", "제자리 볼 핸들링", "2026-W38", "쉬웠음")  # W46 바로 앞 8주(W38~W45)의 가장 오래된 주
    s.add_rating("u", "제자리 볼 핸들링", "2026-W37", "쉬웠음")  # 범위 밖
    s.add_shot("u", "3점 캐치앤슛", "2026-W46", 20, 10)  # 대상 주 자신은 세지 않는다
    s.add_shot("v", "3점 캐치앤슛", "2026-W45", 20, 10)  # 다른 사용자
    counts = field_record_counts(s, "u", "2026-W46", CATALOG)
    assert counts["슛"] == 2 and counts["드리블"] == 2 and counts["레이업"] == 0


# --- 웹 API ---------------------------------------------------------------------------------

def test_the_plan_response_carries_the_recommendation_and_keeps_it_after_confirm(user, env):
    """상급 드리블 메뉴를 쉬웠음으로 기록한 다음 주 계획에 유지 + 추천이 붙는다."""
    env.gen.plan_fn = lambda u, v, j: plan_with("고개 든 드리블", "제자리 볼 핸들링")
    first = make_plan(user, {**FORM, "week": "2026-W45", "level": "상급", "equipment": []}).json()
    assert first["status"] == "confirmed" and first["plan"]["recommendations"] == []
    user.post("/records", json={"drill": "고개 든 드리블", "ratings": ["쉬웠음", "쉬웠음", "쉬웠음"], "week": "2026-W45"})
    draft = user.post("/plans", json={**FORM, "week": "2026-W46", "level": "상급", "equipment": []}).json()
    assert draft["status"] == "pending", draft
    recs = draft["plan"]["recommendations"]
    assert len(recs) == 1 and recs[0]["kept"] == "고개 든 드리블" and recs[0]["field"] != "드리블"
    names = {d["name"] for day in draft["plan"]["days"] for d in day["drills"]}
    assert "고개 든 드리블" in names and recs[0]["menu"] not in names  # 유지했고, 추천은 계획에 없는 메뉴
    done = user.post(f"/plans/{draft['plan_id']}/decision", json={"decision": "confirm"}).json()
    assert done["plan"]["recommendations"] == recs
    assert user.get("/plans/current", params={"week": "2026-W46"}).json()["recommendations"] == recs  # 다시 열어도 같다


def test_no_recommendation_when_the_raise_can_still_go_up(user, env):
    env.gen.plan_fn = lambda u, v, j: plan_with("제자리 볼 핸들링", "양손 크로스오버 드리블")
    make_plan(user, {**FORM, "week": "2026-W45", "level": "초급", "equipment": []})
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["쉬웠음", "쉬웠음"], "week": "2026-W45"})
    env.gen.plan_fn = lambda u, v, j: plan_with("양손 크로스오버 드리블", "이동 크로스오버 드리블")
    r = make_plan(user, {**FORM, "week": "2026-W46", "level": "초급", "equipment": []}).json()
    assert r["status"] == "confirmed" and r["plan"]["recommendations"] == []
