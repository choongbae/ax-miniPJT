import json
from pathlib import Path

from src.models import Drill

DRILLS_PATH = Path(__file__).resolve().parent.parent / "data" / "drills.json"


def load_drills() -> list[Drill]:
    return [Drill.model_validate(d) for d in json.loads(DRILLS_PATH.read_text(encoding="utf-8"))]


def test_twenty_nine_drills_with_all_required_fields():
    drills = load_drills()  # 필수 필드나 수준 값이 틀리면 여기서 오류가 난다
    assert len(drills) == 29
    assert all(d.name and d.purpose for d in drills)


def test_names_are_unique():
    names = [d.name for d in load_drills()]
    assert len(names) == len(set(names))


def test_both_shooting_and_non_shooting_drills_exist():
    drills = load_drills()
    assert any(d.is_shooting for d in drills)
    assert any(not d.is_shooting for d in drills)


def test_drills_needing_hoop_and_not_needing_hoop_exist():
    drills = load_drills()
    assert any("골대" in d.requires for d in drills)
    assert any("골대" not in d.requires for d in drills)


def test_every_shooting_drill_needs_a_hoop():
    assert all("골대" in d.requires for d in load_drills() if d.is_shooting)


def test_beginner_drills_available_with_ball_only():
    # 케이스 6: 초급, 골대 없이 공만 있어도 계획을 짤 수 있어야 한다
    ball_only = [d for d in load_drills() if d.difficulty == "초급" and not d.requires]
    assert ball_only


def test_ball_only_beginner_menus_cover_the_three_basics():
    # 초보자 옵션(공만 있는 경우): 슛 폼, 볼 핸들링, 레이업 기초를 모두 할 수 있어야 한다
    names = {d.name for d in load_drills() if d.difficulty == "초급" and not d.requires}
    assert len(names) >= 7
    assert "슛 폼 연습" in names
    assert "레이업 스텝 연습" in names
    assert {"제자리 볼 핸들링", "제자리 한 손 드리블", "걸으며 드리블", "다리 사이 8자 드리블"} <= names


def test_ball_only_intermediate_menus_are_varied():
    # 공만 있는 중급 사용자도 같은 메뉴가 반복되지 않도록 여러 개가 있어야 한다
    names = {d.name for d in load_drills() if d.difficulty == "중급" and not d.requires}
    assert len(names) >= 7
    assert {"이동 크로스오버 드리블", "유로스텝 연습", "한 손 슛 폼 연습"} <= names


def test_form_practice_menus_are_not_scored_shooting():
    # 골대 없이 하는 슛 폼·레이업 스텝은 성공률을 기록하지 않으므로 슛 외 메뉴다
    by_name = {d.name: d for d in load_drills()}
    for name in ["슛 폼 연습", "레이업 스텝 연습", "한 손 슛 폼 연습", "유로스텝 연습"]:
        assert not by_name[name].is_shooting


def test_all_three_levels_present():
    assert {d.difficulty for d in load_drills()} == {"초급", "중급", "상급"}
