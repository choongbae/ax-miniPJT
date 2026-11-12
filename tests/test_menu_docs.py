"""data/menus/*.md 연습 메뉴 문서와 data/drills.json이 서로 맞는지 확인한다."""
from pathlib import Path

from src.tools import load_drills

MENUS_DIR = Path(__file__).resolve().parent.parent / "data" / "menus"
REQUIRED_SECTIONS = ["## 하는 법", "## 자세 팁", "## 흔한 실수", "## 왜 이렇게 하나요", "## 이런 사람에게 좋아요"]


def parse(path: Path) -> tuple[dict, str]:
    """맨 위 ---로 둘러싼 머리말과 본문으로 나눈다."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path.name}: 머리말이 없다"
    head, body = text[4:].split("\n---\n", 1)
    meta = dict(line.split(": ", 1) for line in head.splitlines())
    return meta, body


def all_docs() -> list[tuple[Path, dict, str]]:
    return [(p, *parse(p)) for p in sorted(MENUS_DIR.glob("*.md"))]


def test_between_20_and_30_documents():
    assert 20 <= len(all_docs()) <= 30


def test_every_menu_has_exactly_one_document():
    names = [m["name"] for _, m, _ in all_docs()]
    assert len(names) == len(set(names))
    assert set(names) == {d.name for d in load_drills()}


def test_doc_ids_are_unique_and_match_file_names():
    ids = [m["doc_id"] for _, m, _ in all_docs()]
    assert len(ids) == len(set(ids))
    for path, meta, _ in all_docs():
        assert meta["doc_id"] == path.stem


def test_front_matter_matches_drills_json():
    by_name = {d.name: d for d in load_drills()}
    for path, meta, _ in all_docs():
        d = by_name[meta["name"]]
        assert meta["difficulty"] == d.difficulty, path.name
        assert meta["is_shooting"] == ("true" if d.is_shooting else "false"), path.name
        requires = [] if meta["requires"] == "없음" else meta["requires"].split(", ")
        assert set(requires) == set(d.requires), path.name


def test_every_document_has_all_sections_and_the_purpose():
    by_name = {d.name: d for d in load_drills()}
    for path, meta, body in all_docs():
        for section in REQUIRED_SECTIONS:
            assert section in body, f"{path.name}: {section} 없음"
        assert by_name[meta["name"]].purpose in body, path.name
        assert "추천 포지션:" in body and "보완할 약점:" in body, path.name


def test_each_section_has_at_least_two_items():
    for path, _, body in all_docs():
        steps = body.split("## 하는 법")[1].split("##")[0]
        tips = body.split("## 자세 팁")[1].split("##")[0]
        mistakes = body.split("## 흔한 실수")[1].split("##")[0]
        assert sum(1 for l in steps.splitlines() if l[:2].rstrip(".").isdigit()) >= 2, path.name
        assert tips.count("\n- ") >= 2, path.name
        assert mistakes.count("\n- ") >= 2, path.name


def test_levels_and_positions_are_spread_out():
    docs = all_docs()
    levels = [m["difficulty"] for _, m, _ in docs]
    for level in ("초급", "중급", "상급"):
        assert levels.count(level) >= 5, f"{level} 문서가 5개 미만"
    for pos in ("가드", "포워드", "센터"):
        assert sum(1 for _, _, body in docs if pos in body.split("추천 포지션:")[1]) >= 8, f"{pos} 추천 문서가 8개 미만"


def test_each_kind_of_weakness_is_covered_at_every_level_it_matters():
    # 슛·드리블·레이업·패스 약점을 풀어 줄 문서가 모두 있다
    all_text = "\n".join(body for _, _, body in all_docs())
    for keyword in ("3점슛", "자유투", "드리블", "레이업", "패스", "슛 폼", "풋워크"):
        assert keyword in all_text, f"'{keyword}' 약점을 다루는 문서가 없다"
