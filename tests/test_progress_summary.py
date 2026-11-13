"""분야별 종합표 (T44): 기록이 있는 가장 최근 주를 기준으로 다섯 분야를 한눈에 본다. 계산은 코드가 한다."""
from fastapi.testclient import TestClient

from src.progress import FIELDS, build_progress, build_summary
from src.tools import load_drills
from tests.test_web import FORM, env, make_plan, signup, user  # noqa: F401

CATALOG = load_drills()
WEEKS = [f"2026-W{n}" for n in range(39, 47)]  # W39 ~ W46 (이번 주 = W46)


def summary_of(records):
    fields = build_progress(records, CATALOG, WEEKS)
    return build_summary(fields, WEEKS), fields


def row(summary, name):
    return next(r for r in summary["rows"] if r["field"] == name)


# --- 기준 주 ----------------------------------------------------------------------------------

def test_the_base_week_is_the_latest_week_with_any_record():
    s, _ = summary_of({"2026-W42": {"3점 캐치앤슛": {"shots": [(50, 25)], "ratings": []}}, "2026-W44": {"제자리 볼 핸들링": {"shots": [], "ratings": ["쉬웠음"]}}})
    assert s["base_week"] == "2026-W44" and s["is_current"] is False  # 이번 주(W46)에는 기록이 없다


def test_the_base_week_is_this_week_when_it_has_records():
    s, _ = summary_of({"2026-W46": {"제자리 볼 핸들링": {"shots": [], "ratings": ["적당"]}}, "2026-W44": {"3점 캐치앤슛": {"shots": [(50, 25)], "ratings": []}}})
    assert s["base_week"] == "2026-W46" and s["is_current"] is True


def test_without_any_record_the_base_week_is_this_week():
    s, _ = summary_of({})
    assert s["base_week"] == "2026-W46" and s["is_current"] is True and s["fields_with_data"] == 0
    assert [r["field"] for r in s["rows"]] == list(FIELDS)
    assert all(not r["has_data"] and not r["base_has_records"] and r["trend_status"] == "none" and r["recorded_weeks"] == 0 and r["last_recorded_week"] is None for r in s["rows"])


def test_records_older_than_the_shown_weeks_do_not_count():
    s, _ = summary_of({"2026-W30": {"3점 캐치앤슛": {"shots": [(50, 25)], "ratings": []}}})  # 보이는 W39~W46 밖
    assert s["fields_with_data"] == 0 and s["base_week"] == "2026-W46"


# --- 분야별 값 --------------------------------------------------------------------------------

def test_each_field_shows_its_values_for_the_base_week():
    records = {
        "2026-W45": {
            "3점 캐치앤슛": {"shots": [(30, 12), (20, 10)], "ratings": []},  # 합쳐서 50회 중 22회(44%)
            "제자리 자유투": {"shots": [(50, 40)], "ratings": []},
            "제자리 볼 핸들링": {"shots": [], "ratings": ["쉬웠음", "쉬웠음", "적당"]},
            "벽 패스": {"shots": [], "ratings": ["어려웠음"]},
        },
        "2026-W43": {"양손 레이업": {"shots": [], "ratings": ["적당"]}},
    }
    s, _ = summary_of(records)
    assert s["base_week"] == "2026-W45"
    shot = row(s, "슛")
    assert shot["attempts"] == 100 and shot["makes"] == 62 and shot["rate"] == 62.0 and shot["enough"] is True and shot["base_has_records"]
    assert shot["verdicts"] == {"상향": 1, "유지": 1, "하향": 0}  # 3점 캐치앤슛 50회 중 22회(44%) 유지, 자유투 80% 상향
    drib = row(s, "드리블")
    assert drib["rating_count"] == 3 and drib["rating_avg"] == 2.67 and drib["verdicts"]["상향"] == 1
    assert row(s, "패스")["rating_avg"] == 1.0 and row(s, "패스")["verdicts"]["하향"] == 1
    assert s["fields_with_data"] == 4  # 슛, 드리블, 패스, 레이업(W43)


def test_a_field_without_records_in_the_base_week_still_shows_when_it_last_had_some():
    s, _ = summary_of({"2026-W45": {"제자리 볼 핸들링": {"shots": [], "ratings": ["적당"]}}, "2026-W42": {"양손 레이업": {"shots": [], "ratings": ["쉬웠음"]}}})
    layup = row(s, "레이업")
    assert layup["has_data"] and not layup["base_has_records"] and layup["rating_avg"] is None and layup["last_recorded_week"] == "2026-W42"
    assert layup["recorded_weeks"] == 1


def test_recorded_weeks_counts_weeks_with_records_inside_the_shown_range():
    records = {w: {"제자리 볼 핸들링": {"shots": [], "ratings": ["적당"]}} for w in ("2026-W40", "2026-W41", "2026-W45")}
    r = row(summary_of(records)[0], "드리블")
    assert r["recorded_weeks"] == 3 and r["last_recorded_week"] == "2026-W45"


# --- 추이 -------------------------------------------------------------------------------------

def test_the_trend_uses_the_shot_rate_when_the_field_has_shots_otherwise_the_rating():
    records = {}
    for w in WEEKS[:4]:
        records[w] = {"3점 캐치앤슛": {"shots": [(50, 20)], "ratings": []}, "제자리 볼 핸들링": {"shots": [], "ratings": ["적당", "적당", "적당"]}}
    for w in WEEKS[4:]:
        records[w] = {"3점 캐치앤슛": {"shots": [(50, 30)], "ratings": []}, "제자리 볼 핸들링": {"shots": [], "ratings": ["쉬웠음", "쉬웠음", "쉬웠음"]}}
    s, fields = summary_of(records)
    shot, drib = row(s, "슛"), row(s, "드리블")
    assert shot["trend_kind"] == "성공률" and shot["trend_status"] == "up" and "올랐어요" in shot["trend_text"]
    assert drib["trend_kind"] == "체감 난이도" and drib["trend_status"] == "up" and "쉬워졌어요" in drib["trend_text"]
    assert next(f for f in fields if f["field"] == "슛")["shot_trend"]["text"] == shot["trend_text"]  # 분야 카드와 같은 문장
    assert row(s, "패스")["trend_kind"] is None and row(s, "패스")["trend_status"] == "none"


def test_a_field_with_both_shots_and_ratings_prefers_the_shot_rate():
    records = {w: {"3점 캐치앤슛": {"shots": [(50, 25)], "ratings": []}, "슛 폼 연습": {"shots": [], "ratings": ["적당"]}} for w in WEEKS}
    assert row(summary_of(records)[0], "슛")["trend_kind"] == "성공률"


# --- API --------------------------------------------------------------------------------------

def test_progress_response_has_the_summary(user):
    body = user.get("/progress").json()
    s = body["summary"]
    assert s["base_week"] == "2026-W46" and s["is_current"] is True and s["fields_with_data"] == 0
    assert [r["field"] for r in s["rows"]] == list(FIELDS)


def test_the_summary_follows_the_latest_week_with_records(user):
    make_plan(user, {**FORM, "week": "2026-W44"})
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["쉬웠음"], "week": "2026-W44", "slot": "월"})
    s = user.get("/progress").json()["summary"]
    assert s["base_week"] == "2026-W44" and s["is_current"] is False and s["fields_with_data"] == 1
    drib = next(r for r in s["rows"] if r["field"] == "드리블")
    assert drib["rating_avg"] == 3.0 and drib["verdicts"]["상향"] == 1 and drib["recorded_weeks"] == 1 and drib["last_recorded_week"] == "2026-W44"
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["적당"], "slot": "월"})  # 이번 주(W46)에도 기록
    assert user.get("/progress").json()["summary"]["base_week"] == "2026-W46"


def test_the_summary_is_per_user(env, user):
    make_plan(user, FORM)
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["적당"], "slot": "월"})
    other = TestClient(env.app)
    signup(other, "jisu")
    assert other.get("/progress").json()["summary"]["fields_with_data"] == 0
    assert user.get("/progress").json()["summary"]["fields_with_data"] == 1


def test_the_summary_respects_the_weeks_parameter_range(user):
    make_plan(user, {**FORM, "week": "2026-W35"})
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["적당"], "week": "2026-W35", "slot": "월"})
    assert user.get("/progress", params={"weeks": 8}).json()["summary"]["fields_with_data"] == 0  # W39~W46 밖
    assert user.get("/progress", params={"weeks": 12}).json()["summary"]["base_week"] == "2026-W35"


# --- 방사형 차트 (T45): 분야별 0~100 점수, 기준 주 vs 4주 전 ---------------------------------------

from src.progress import radar_score  # noqa: E402


def axis(summary, name):
    return next(a for a in summary["radar"]["axes"] if a["field"] == name)


def test_radar_score_uses_the_shot_rate_or_converts_the_rating_average():
    base = {"attempts": 0, "makes": 0, "rate": None, "enough": False, "rating_count": 0, "rating_avg": None}
    assert radar_score({**base, "attempts": 50, "makes": 30, "rate": 60.0, "enough": True}) == (60.0, False)  # 성공률 그대로
    assert radar_score({**base, "attempts": 15, "makes": 3, "rate": 20.0, "enough": False}) == (20.0, True)  # 표본이 적다
    assert radar_score({**base, "rating_count": 3, "rating_avg": 1.0}) == (0.0, False)  # 어려웠음만
    assert radar_score({**base, "rating_count": 3, "rating_avg": 2.0}) == (50.0, False)  # 적당
    assert radar_score({**base, "rating_count": 3, "rating_avg": 3.0}) == (100.0, False)  # 쉬웠음
    assert radar_score({**base, "rating_count": 3, "rating_avg": 2.67}) == (83.5, False)  # (2.67 - 1) / 2 * 100
    assert radar_score({**base, "rating_count": 1, "rating_avg": 3.0}) == (100.0, True)  # 평가 3건 미만은 표본이 적다
    assert radar_score(base) == (None, False)  # 기록 없음은 0점이 아니다


def test_radar_prefers_the_shot_rate_when_a_field_has_both():
    base = {"attempts": 50, "makes": 20, "rate": 40.0, "enough": True, "rating_count": 3, "rating_avg": 3.0}
    assert radar_score(base) == (40.0, False)


def test_radar_compares_the_base_week_with_four_weeks_before():
    records = {
        "2026-W42": {"3점 캐치앤슛": {"shots": [(50, 20)], "ratings": []}, "제자리 볼 핸들링": {"shots": [], "ratings": ["적당"]}},
        "2026-W46": {"3점 캐치앤슛": {"shots": [(50, 30)], "ratings": []}, "제자리 볼 핸들링": {"shots": [], "ratings": ["쉬웠음"]}, "양손 레이업": {"shots": [], "ratings": ["어려웠음"]}},
    }
    s, _ = summary_of(records)
    radar = s["radar"]
    assert radar["base_week"] == "2026-W46" and radar["compare_week"] == "2026-W42" and radar["min_axes"] == 3
    assert [a["field"] for a in radar["axes"]] == list(FIELDS)
    shot, drib, layup = axis(s, "슛"), axis(s, "드리블"), axis(s, "레이업")
    assert (shot["previous"], shot["current"]) == (40.0, 60.0) and shot["current_thin"] is False
    assert (drib["previous"], drib["current"]) == (50.0, 100.0) and drib["current_thin"] is True  # 평가 한 건뿐이라 참고만
    assert layup["previous"] is None and layup["current"] == 0.0  # 4주 전 기록이 없으면 점 없음, 어려웠음은 0점
    assert axis(s, "패스")["current"] is None and axis(s, "기타")["current"] is None  # 기록 없는 분야는 점이 없다 (0이 아니다)
    assert radar["axes_with_data"] == 3


def test_radar_follows_the_latest_week_with_records():
    s, _ = summary_of({"2026-W44": {"제자리 볼 핸들링": {"shots": [], "ratings": ["적당"]}}, "2026-W40": {"제자리 볼 핸들링": {"shots": [], "ratings": ["쉬웠음"]}}})
    radar = s["radar"]
    assert radar["base_week"] == "2026-W44" == s["base_week"] and radar["compare_week"] == "2026-W40"
    assert (axis(s, "드리블")["previous"], axis(s, "드리블")["current"]) == (100.0, 50.0)


def test_radar_has_no_compare_week_when_it_falls_outside_the_shown_range():
    s, _ = summary_of({"2026-W41": {"제자리 볼 핸들링": {"shots": [], "ratings": ["적당"]}}})  # W41의 4주 전은 W37(보이는 범위 밖)
    assert s["radar"]["base_week"] == "2026-W41" and s["radar"]["compare_week"] is None
    assert axis(s, "드리블")["previous"] is None and axis(s, "드리블")["current"] == 50.0


def test_radar_without_records_has_no_points():
    s, _ = summary_of({})
    assert s["radar"]["axes_with_data"] == 0 and all(a["current"] is None and a["previous"] is None for a in s["radar"]["axes"])


def test_radar_goes_through_the_api(user):
    make_plan(user, {**FORM, "week": "2026-W42"})
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["적당"], "week": "2026-W42", "slot": "월"})
    make_plan(user, FORM)
    user.post("/records", json={"drill": "제자리 볼 핸들링", "ratings": ["쉬웠음"], "slot": "월"})
    radar = user.get("/progress").json()["summary"]["radar"]
    assert radar["base_week"] == "2026-W46" and radar["compare_week"] == "2026-W42" and radar["axes_with_data"] == 1
    drib = next(a for a in radar["axes"] if a["field"] == "드리블")
    assert drib["previous"] == 50.0 and drib["current"] == 100.0
    assert set(radar["axes"][0]) == {"field", "current", "previous", "current_thin", "previous_thin"}
