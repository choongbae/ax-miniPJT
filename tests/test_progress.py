"""분야별 실력 현황 (T36): 분야 나누기, 주별 값, 추이 비교, API. 모든 값은 코드로 계산한다."""
import pytest
from fastapi.testclient import TestClient

from src.progress import (
    FIELDS, RATING_TREND_DELTA, SHOT_TREND_DELTA, build_progress, field_of, rating_trend, shot_trend,
)
from src.tools import load_drills
from tests.test_web import FORM, env, make_plan, signup, user  # noqa: F401

CATALOG = load_drills()
BY = {d.name: d for d in CATALOG}
WEEKS = [f"2026-W{n}" for n in range(39, 47)]  # W39 ~ W46 (8주)


def field(progress, name):
    return next(f for f in progress if f["field"] == name)


# --- 분야 나누기 ------------------------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("3점 캐치앤슛", "슛"), ("제자리 자유투", "슛"), ("풀업 점퍼", "슛"), ("드리블 풀업 3점", "슛"),  # 슛 연습 메뉴는 이름에 드리블이 있어도 슛
    ("슛 폼 연습", "슛"), ("한 손 슛 폼 연습", "슛"),
    ("양손 레이업", "레이업"), ("레이업 스텝 연습", "레이업"), ("시간 제한 레이업 연속 마무리", "레이업"),
    ("제자리 볼 핸들링", "드리블"), ("양손 크로스오버 드리블", "드리블"),
    ("벽 패스", "패스"), ("피벗 연습", "기타"), ("점프 스톱 연습", "기타"),
])
def test_drills_are_split_into_fields_by_rule(name, expected):
    assert field_of(BY[name]) == expected


def test_every_drill_belongs_to_exactly_one_known_field():
    assert {field_of(d) for d in CATALOG} == set(FIELDS)  # 다섯 분야 모두 연습 메뉴가 있다


# --- 주별 값 ----------------------------------------------------------------------------------

def test_weekly_shot_and_rating_values_are_computed_per_field():
    records = {
        "2026-W45": {"3점 캐치앤슛": {"shots": [(30, 12), (20, 10)], "ratings": []}, "제자리 자유투": {"shots": [(50, 40)], "ratings": []}},
        "2026-W46": {"제자리 볼 핸들링": {"shots": [], "ratings": ["쉬웠음", "적당", "적당"]}, "양손 크로스오버 드리블": {"shots": [], "ratings": ["어려웠음"]}},
    }
    p = build_progress(records, CATALOG, WEEKS)
    shot = {r["week"]: r for r in field(p, "슛")["weeks"]}
    assert shot["2026-W45"]["attempts"] == 100 and shot["2026-W45"]["makes"] == 62 and shot["2026-W45"]["rate"] == 62.0
    assert shot["2026-W45"]["enough"] is True and shot["2026-W45"]["drills_recorded"] == 2
    assert shot["2026-W44"]["rate"] is None and shot["2026-W44"]["drills_recorded"] == 0  # 기록 없는 주는 값이 없다
    dribble = {r["week"]: r for r in field(p, "드리블")["weeks"]}["2026-W46"]
    assert dribble["rating_count"] == 4 and dribble["rating_avg"] == 2.0  # (3+2+2+1)/4
    assert field(p, "패스")["has_data"] is False and field(p, "슛")["has_data"] and field(p, "드리블")["has_data"]
    assert [r["week"] for r in field(p, "슛")["weeks"]] == WEEKS  # 오래된 주부터


def test_a_small_sample_is_flagged_not_hidden():
    p = build_progress({"2026-W46": {"3점 캐치앤슛": {"shots": [(15, 3)], "ratings": []}}}, CATALOG, WEEKS)
    row = field(p, "슛")["weeks"][-1]
    assert row["rate"] == 20.0 and row["enough"] is False


def test_next_week_verdicts_use_the_same_rule_as_judge_drill_including_the_past_correction():
    # 200회 중 79회(39.5%)는 보정이 없으면 하향, 3주 전에 45%였으면 유지 (SERVICE.md 규칙)
    alone = build_progress({"2026-W46": {"3점 캐치앤슛": {"shots": [(200, 79)], "ratings": []}}}, CATALOG, WEEKS)
    assert field(alone, "슛")["weeks"][-1]["verdicts"] == {"상향": 0, "유지": 0, "하향": 1}
    corrected = build_progress(
        {"2026-W46": {"3점 캐치앤슛": {"shots": [(200, 79)], "ratings": []}}, "2026-W43": {"3점 캐치앤슛": {"shots": [(100, 45)], "ratings": []}}},
        CATALOG, WEEKS,
    )
    assert field(corrected, "슛")["weeks"][-1]["verdicts"] == {"상향": 0, "유지": 1, "하향": 0}


def test_past_correction_can_use_weeks_before_the_shown_range():
    # 보이는 첫 주(W39)보다 앞선 W38 기록도 판정 보정에 쓴다
    records = {"2026-W39": {"3점 캐치앤슛": {"shots": [(200, 79)], "ratings": []}}, "2026-W38": {"3점 캐치앤슛": {"shots": [(100, 45)], "ratings": []}}}
    assert field(build_progress(records, CATALOG, WEEKS), "슛")["weeks"][0]["verdicts"]["유지"] == 1


# --- 추이 -------------------------------------------------------------------------------------

def shot_rows(sessions):
    """sessions: 주마다 (시도, 성공) 또는 None."""
    out = []
    for s in sessions:
        a, m = s or (0, 0)
        out.append({"attempts": a, "makes": m, "rate": None, "enough": False, "rating_count": 0, "rating_avg": None, "verdicts": {}, "drills_recorded": 0})
    return out


def test_shot_trend_up_down_flat_with_the_3_point_threshold():
    base = [(50, 20)] * 4  # 40.0%
    up = shot_trend(shot_rows(base + [(50, 25)] * 4))  # 50.0%, +10.0
    assert up["status"] == "up" and up["diff"] == 10.0 and up["recent"] == 50.0 and up["previous"] == 40.0 and "올랐어요" in up["text"]
    down = shot_trend(shot_rows([(50, 25)] * 4 + base))
    assert down["status"] == "down" and down["diff"] == -10.0 and "내려갔어요" in down["text"]
    assert shot_trend(shot_rows(base + [(50, 21)] * 4))["status"] == "flat"  # +2.0은 임계값 3.0 미만
    edge = shot_trend(shot_rows([(100, 40)] * 4 + [(100, 43)] * 4))  # 정확히 +3.0은 오른 것으로 본다
    assert edge["status"] == "up" and edge["diff"] == SHOT_TREND_DELTA


def test_shot_trend_pools_attempts_so_big_weeks_count_more():
    # 한 주 200회 70%와 세 주 10회 0%: 합치면 70/230 = 30.4% (주별 평균 17.5%가 아니다)
    rows = shot_rows([(200, 140), (10, 0), (10, 0), (10, 0)] + [(50, 50)] * 4)
    t = shot_trend(rows)
    assert t["previous"] == 60.9 and t["recent"] == 100.0  # (140)/(230) = 60.9%


def test_shot_trend_needs_enough_attempts_in_both_windows():
    few = shot_trend(shot_rows([(4, 2)] * 4 + [(50, 25)] * 4))  # 앞 4주 합계가 16회로 20회 미만
    assert few["status"] == "insufficient" and few["diff"] is None and "기록이 더 필요해요" in few["text"]
    assert shot_trend(shot_rows([None] * 8))["status"] == "none"
    assert shot_trend(shot_rows([(50, 25)] * 4))["status"] == "insufficient"  # 앞 구간이 없다
    assert shot_trend(shot_rows([(30, 15)] * 8))["status"] == "flat"


def rating_rows(avgs):
    return [{"attempts": 0, "makes": 0, "rate": None, "enough": False, "rating_count": 0 if a is None else 2, "rating_avg": a, "verdicts": {}, "drills_recorded": 0} for a in avgs]


def test_rating_trend_direction_means_easier_or_harder():
    up = rating_trend(rating_rows([2.0] * 4 + [2.5] * 4))
    assert up["status"] == "up" and up["diff"] == 0.5 and "쉬워졌어요" in up["text"]
    down = rating_trend(rating_rows([2.5] * 4 + [2.0] * 4))
    assert down["status"] == "down" and "어려워졌어요" in down["text"]
    assert rating_trend(rating_rows([2.0] * 4 + [2.2] * 4))["status"] == "flat"  # +0.2는 임계값 0.3 미만
    assert rating_trend(rating_rows([2.0] * 4 + [2.3] * 4))["diff"] == RATING_TREND_DELTA  # 정확히 0.3은 쉬워졌다
    assert rating_trend(rating_rows([None] * 8))["status"] == "none"
    assert rating_trend(rating_rows([None] * 4 + [2.0] + [None] * 3))["status"] == "insufficient"  # 평가 건수 부족


# --- API --------------------------------------------------------------------------------------

def test_progress_requires_login(env):
    assert TestClient(env.app).get("/progress").status_code == 401


def test_progress_is_empty_but_well_formed_without_records(user):
    body = user.get("/progress").json()
    assert body["current"] == "2026-W46" and body["weeks"][-1] == "2026-W46" and len(body["weeks"]) == 8
    assert [f["field"] for f in body["fields"]] == list(FIELDS)
    assert all(not f["has_data"] and f["shot_trend"]["status"] == "none" and len(f["weeks"]) == 8 for f in body["fields"])


def test_progress_reflects_records_entered_through_the_web_api(user):
    make_plan(user, FORM)
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["쉬웠음"]})
    make_plan(user, {**FORM, "week": "2026-W44"})
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["어려웠음"], "week": "2026-W44"})
    drib = field(user.get("/progress").json()["fields"], "드리블")
    rows = {r["week"]: r for r in drib["weeks"]}
    assert rows["2026-W46"]["rating_avg"] == 3.0 and rows["2026-W44"]["rating_avg"] == 1.0
    assert rows["2026-W46"]["verdicts"]["상향"] == 1 and rows["2026-W44"]["verdicts"]["하향"] == 1


def test_progress_is_per_user(env, user):
    make_plan(user, FORM)
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["쉬웠음"]})
    other = TestClient(env.app)
    signup(other, "jisu")
    assert not any(f["has_data"] for f in other.get("/progress").json()["fields"])
    assert any(f["has_data"] for f in user.get("/progress").json()["fields"])


@pytest.mark.parametrize("weeks,ok", [(4, True), (8, True), (26, True), (3, False), (27, False), (0, False)])
def test_weeks_parameter_is_bounded(user, weeks, ok):
    r = user.get("/progress", params={"weeks": weeks})
    assert (r.status_code == 200) is ok
    if ok:
        assert len(r.json()["weeks"]) == weeks


def test_the_range_ends_at_the_current_week_and_never_includes_future_weeks(user, env):
    from tests.test_web import W47

    env.clock.today = W47
    assert user.get("/progress").json()["weeks"][-1] == "2026-W47"
