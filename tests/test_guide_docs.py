"""data/guides/*.md 안내 문서와, 안내 문서가 섞인 검색을 확인한다."""
from pathlib import Path

from src.agent import select_menus
from src.models import UserInput
from src.retriever import load_guide_docs, load_menu_docs, parse_menu_doc
from src.tools import load_drills

GUIDES_DIR = Path(__file__).resolve().parent.parent / "data" / "guides"
CATALOG = load_drills()


def test_there_are_guide_documents_with_unique_ids():
    guides = load_guide_docs()
    assert len(guides) >= 8
    ids = [g.doc_id for g in guides] + [m.doc_id for m in load_menu_docs()]
    assert len(ids) == len(set(ids))  # 메뉴 문서와도 겹치지 않는다


def test_guides_have_kind_and_no_menu_fields():
    for g in load_guide_docs():
        assert g.kind == "guide"
        assert g.difficulty == "" and g.requires == () and g.is_shooting is False
        assert g.doc_id == next(p for p in GUIDES_DIR.glob("*.md") if p.stem == g.doc_id).stem


def test_menus_keep_menu_kind():
    assert all(m.kind == "menu" for m in load_menu_docs())


def test_every_guide_has_a_title_and_enough_body():
    for path in GUIDES_DIR.glob("*.md"):
        doc = parse_menu_doc(path)
        assert doc.text.startswith("# "), path.name
        assert len(doc.text) >= 300, path.name


def test_glossary_defines_the_terms_the_menu_documents_use():
    guides = {g.doc_id: g.text for g in load_guide_docs()}
    shooting = guides["glossary-shooting"]
    footwork = guides["glossary-dribble-footwork"]
    rules = guides["rules-basics"]
    for term in ("슛 포켓", "릴리스", "팔로우스루", "백스핀", "캐치앤슛", "페이드어웨이", "오프더볼"):
        assert f"- {term}:" in shooting, term
    for term in ("크로스오버", "비하인드 더 백", "인앤아웃", "체인지 오브 페이스", "축발", "피벗", "점프 스톱", "유로스텝", "풋워크"):
        assert f"- {term}:" in footwork, term
    for term in ("트래블링", "더블 드리블", "3초 룰", "3점 라인"):
        assert f"- {term}:" in rules, term


def test_why_explanations_exist_for_backspin_and_follow_through():
    text = {g.doc_id: g.text for g in load_guide_docs()}["shooting-principles"]
    assert "백스핀이 필요한 이유" in text and "팔로우스루가 필요한 이유" in text


def test_warmup_guide_is_not_medical_advice():
    text = {g.doc_id: g.text for g in load_guide_docs()}["warmup-cooldown"]
    assert "진단" in text and "전문가" in text


def test_difficulty_rules_guide_matches_the_service_rules():
    text = {g.doc_id: g.text for g in load_guide_docs()}["difficulty-rules"]
    for fragment in ("40% 미만", "60% 이상", "20회 미만", "최근 4주", "동수이면 유지", "다시 넣습니다"):
        assert fragment in text, fragment


def test_every_menu_has_a_why_section_with_a_sentence():
    for m in load_menu_docs():
        why = m.text.split("## 왜 이렇게 하나요")[1].split("##")[0].strip()
        assert len(why) >= 30, m.doc_id


# --- 검색에 안내 문서가 섞여도 계획용 검색은 영향을 받지 않는다 ---------------------

def test_guides_are_searchable_and_found_by_topic(retriever):
    names = {r.doc.doc_id for r in retriever.search("백스핀이 왜 필요해 슛 원리", kinds=["guide"], k=3)}
    assert "shooting-principles" in names or "glossary-shooting" in names


def test_kinds_filter_separates_menus_and_guides(retriever):
    assert all(r.doc.kind == "guide" for r in retriever.search("연습", kinds=["guide"], k=50))
    assert all(r.doc.kind == "menu" for r in retriever.search("연습", kinds=["menu"], k=50))


def test_equipment_and_level_filters_do_not_hide_guides(retriever):
    res = retriever.search("규칙 트래블링", equipment=[], levels=["초급"], kinds=["guide"], k=50)
    assert len(res) == len(load_guide_docs())


def test_max_distance_drops_far_documents(retriever):
    everything = retriever.search("슛 폼", k=100)
    near = retriever.search("슛 폼", k=100, max_distance=everything[2].distance)
    assert 1 <= len(near) <= 3
    assert all(r.distance <= everything[2].distance for r in near)


def test_planning_search_never_returns_guides(retriever):
    user = UserInput(position="가드", level="중급", goals=["3점슛"], days_per_week=3, minutes_per_session=40, equipment=["골대", "콘"])
    menus, contexts = select_menus(user, CATALOG, retriever)
    menu_ids = {m.doc_id for m in load_menu_docs()}
    assert contexts and all(c["doc_id"] in menu_ids for c in contexts)
