"""분야별 실력 현황 (T36). 쌓인 연습 기록으로 분야마다 주별 변화를 계산한다. 모든 계산은 코드가 하고 모델은 쓰지 않는다.

분야는 연습 메뉴로 나눈다 (처음 맞는 것): 슛 연습 메뉴(is_shooting) -> 슛, 이름에 '레이업' -> 레이업, '드리블'·'핸들링' -> 드리블,
'패스' -> 패스, 이름에 '슛' -> 슛, 나머지 -> 기타.

주별 값
- 슛: 시도·성공·성공률(소수 첫째 자리), 시도가 20회 미만이면 표본이 적다(enough=False)
- 자기평가: 쉬웠음 3·적당 2·어려웠음 1점의 평균 (점수가 높을수록 쉬워진 것, 곧 익숙해진 것)
- 다음 주 난이도 판정(상향·유지·하향) 건수: 그 주 기록이 있는 연습 메뉴마다 `judge_drill`(앞 4주 보정 포함)로 센다
- 추이: 최근 4주와 그 앞 4주를 합쳐서 비교한다. 슛은 성공률 차이 3.0%p 이상이면 늘었다/줄었다, 평가는 평균 0.3점 이상이면 쉬워졌다/어려워졌다,
  그보다 작으면 비슷하다. 두 구간 모두 슛 20회 이상(평가 3건 이상)이 아니면 비교하지 않는다.
"""
from src.models import Drill
from src.records import previous_week_keys
from src.tools import MIN_SHOT_ATTEMPTS, judge_drill

FIELDS = ("슛", "드리블", "레이업", "패스", "기타")
SCORE = {"쉬웠음": 3, "적당": 2, "어려웠음": 1}
TREND_WINDOW = 4  # 비교하는 구간 길이(주)
SHOT_TREND_DELTA = 3.0  # %p
RATING_TREND_DELTA = 0.3  # 점
MIN_TREND_RATINGS = 3


def field_of(drill: Drill) -> str:
    if drill.is_shooting:
        return "슛"
    if "레이업" in drill.name:
        return "레이업"
    if "드리블" in drill.name or "핸들링" in drill.name:
        return "드리블"
    if "패스" in drill.name:
        return "패스"
    if "슛" in drill.name:
        return "슛"
    return "기타"


def _rate(makes: int, attempts: int) -> float | None:
    return round(makes / attempts * 100, 1) if attempts > 0 else None


def _past_weeks(records: dict, drill: str, week: str) -> list[tuple[int, int]]:
    """앞 4주 중 슛 기록이 있는 주의 (시도 합, 성공 합). `store.past_weeks`와 같은 규칙."""
    result = []
    for key in previous_week_keys(week, 4):
        sessions = records.get(key, {}).get(drill, {}).get("shots", [])
        if sessions:
            result.append((sum(a for a, _ in sessions), sum(m for _, m in sessions)))
    return result


def _week_row(week: str, drills: list[Drill], records: dict) -> dict:
    attempts = makes = 0
    scores: list[int] = []
    verdicts = {"상향": 0, "유지": 0, "하향": 0}
    recorded = 0
    for drill in drills:
        rec = records.get(week, {}).get(drill.name)
        if not rec or not (rec["shots"] or rec["ratings"]):
            continue
        recorded += 1
        attempts += sum(a for a, _ in rec["shots"])
        makes += sum(m for _, m in rec["shots"])
        scores += [SCORE[r] for r in rec["ratings"] if r in SCORE]
        judgment = judge_drill(drill, shots=rec["shots"], ratings=rec["ratings"], past_weeks=_past_weeks(records, drill.name, week))
        if not judgment.carry_over:
            verdicts[judgment.verdict] += 1
    return {
        "week": week,
        "attempts": attempts,
        "makes": makes,
        "rate": _rate(makes, attempts),
        "enough": attempts >= MIN_SHOT_ATTEMPTS,
        "rating_count": len(scores),
        "rating_avg": round(sum(scores) / len(scores), 2) if scores else None,
        "verdicts": verdicts,
        "drills_recorded": recorded,
    }


def _windows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    recent = rows[-TREND_WINDOW:]
    previous = rows[-2 * TREND_WINDOW : -TREND_WINDOW]
    return recent, previous


def shot_trend(rows: list[dict]) -> dict:
    recent, previous = _windows(rows)
    ra, rm = sum(r["attempts"] for r in recent), sum(r["makes"] for r in recent)
    pa, pm = sum(r["attempts"] for r in previous), sum(r["makes"] for r in previous)
    if ra + pa == 0:
        return {"status": "none", "recent": None, "previous": None, "diff": None, "text": ""}
    recent_rate, previous_rate = _rate(rm, ra), _rate(pm, pa)
    if ra < MIN_SHOT_ATTEMPTS or pa < MIN_SHOT_ATTEMPTS:
        return {
            "status": "insufficient", "recent": recent_rate, "previous": previous_rate, "diff": None,
            "text": f"기록이 더 필요해요. 최근 {TREND_WINDOW}주와 그 앞 {TREND_WINDOW}주 각각 슛을 {MIN_SHOT_ATTEMPTS}회 이상 기록하면 변화를 비교해 드려요.",
        }
    diff = round(recent_rate - previous_rate, 1)
    if diff >= SHOT_TREND_DELTA:
        status, how = "up", f"{diff}%p 올랐어요"
    elif diff <= -SHOT_TREND_DELTA:
        status, how = "down", f"{abs(diff)}%p 내려갔어요"
    else:
        status, how = "flat", f"비슷해요(차이 {abs(diff)}%p)"
    return {
        "status": status, "recent": recent_rate, "previous": previous_rate, "diff": diff,
        "text": f"최근 {TREND_WINDOW}주 성공률은 {recent_rate}%로, 그 앞 {TREND_WINDOW}주({previous_rate}%)보다 {how}." if status != "flat"
        else f"최근 {TREND_WINDOW}주 성공률 {recent_rate}%는 그 앞 {TREND_WINDOW}주({previous_rate}%)와 {how}.",
    }


def rating_trend(rows: list[dict]) -> dict:
    recent, previous = _windows(rows)

    def mean(group: list[dict]) -> tuple[float | None, int]:
        total = sum(r["rating_avg"] * r["rating_count"] for r in group if r["rating_count"])
        n = sum(r["rating_count"] for r in group)
        return (round(total / n, 2) if n else None), n

    recent_avg, rn = mean(recent)
    previous_avg, pn = mean(previous)
    if rn + pn == 0:
        return {"status": "none", "recent": None, "previous": None, "diff": None, "text": ""}
    if rn < MIN_TREND_RATINGS or pn < MIN_TREND_RATINGS:
        return {
            "status": "insufficient", "recent": recent_avg, "previous": previous_avg, "diff": None,
            "text": f"기록이 더 필요해요. 최근 {TREND_WINDOW}주와 그 앞 {TREND_WINDOW}주 각각 자기평가를 {MIN_TREND_RATINGS}건 이상 기록하면 변화를 비교해 드려요.",
        }
    diff = round(recent_avg - previous_avg, 2)
    if diff >= RATING_TREND_DELTA:
        status, how = "up", f"쉬워졌어요(+{diff}점)"
    elif diff <= -RATING_TREND_DELTA:
        status, how = "down", f"어려워졌어요({diff}점)"
    else:
        status, how = "flat", f"비슷해요(차이 {abs(diff)}점)"
    return {
        "status": status, "recent": recent_avg, "previous": previous_avg, "diff": diff,
        "text": f"최근 {TREND_WINDOW}주 체감 난이도 평균은 {recent_avg}점으로, 그 앞 {TREND_WINDOW}주({previous_avg}점)보다 {how}." if status != "flat"
        else f"최근 {TREND_WINDOW}주 체감 난이도 평균 {recent_avg}점은 그 앞 {TREND_WINDOW}주({previous_avg}점)와 {how}.",
    }


def build_progress(records: dict, catalog: list[Drill], weeks: list[str]) -> list[dict]:
    """분야별 현황. records는 `records_for_weeks` 결과로, weeks보다 앞 4주(판정 보정용)까지 담아야 한다. weeks는 오래된 주부터."""
    by_field: dict[str, list[Drill]] = {f: [] for f in FIELDS}
    for drill in catalog:
        by_field[field_of(drill)].append(drill)
    out = []
    for field in FIELDS:
        rows = [_week_row(week, by_field[field], records) for week in weeks]
        out.append(
            {
                "field": field,
                "has_data": any(r["drills_recorded"] for r in rows),
                "weeks": rows,
                "shot_trend": shot_trend(rows),
                "rating_trend": rating_trend(rows),
            }
        )
    return out
