"""검색 구조 테스트. 실제 임베딩 대신 글자 조각을 해시하는 가짜 임베딩을 써서 비용 없이 확인한다."""
from conftest import FakeEmbeddings

from src.retriever import MenuRetriever, load_menu_docs, parse_menu_doc

DOCS = load_menu_docs()


def make(tmp_path, embeddings=None, docs=None):
    return MenuRetriever(docs=docs or DOCS, embeddings=embeddings or FakeEmbeddings(), index_dir=tmp_path / "idx", model_id="fake")


def test_parse_menu_doc_reads_front_matter_and_body():
    doc = next(d for d in DOCS if d.doc_id == "cut-moving-shot")
    assert doc.name == "컷 후 무빙슛"
    assert doc.requires == ("골대", "콘") and doc.difficulty == "상급" and doc.is_shooting
    assert doc.text.startswith("# 컷 후 무빙슛") and "## 하는 법" in doc.text


def test_all_29_docs_are_loaded_and_indexed(tmp_path):
    r = make(tmp_path)
    assert len(DOCS) == 29
    assert r.build() is True
    assert len(r.search("연습", k=100)) == 29


def test_search_finds_documents_about_the_query(tmp_path):
    r = make(tmp_path)
    names = [x.doc.name for x in r.search("3점슛 캐치앤슛 슛 타이밍", k=3)]
    assert "3점 캐치앤슛" in names


def test_search_results_are_sorted_by_distance(tmp_path):
    r = make(tmp_path)
    d = [x.distance for x in r.search("왼손 드리블 약점", k=10)]
    assert d == sorted(d)


def test_equipment_filter_removes_menus_that_need_missing_equipment(tmp_path):
    r = make(tmp_path)
    for x in r.search("3점슛", equipment=[], k=29):
        assert x.doc.requires == ()  # 공만 있는 경우
    with_hoop = {x.doc.name for x in r.search("3점슛", equipment=["골대"], k=29)}
    assert "3점 캐치앤슛" in with_hoop
    assert "컷 후 무빙슛" not in with_hoop  # 콘이 필요


def test_level_filter(tmp_path):
    r = make(tmp_path)
    got = r.search("드리블", levels=["초급"], k=29)
    assert got and all(x.doc.difficulty == "초급" for x in got)


def test_k_limits_results_after_filtering(tmp_path):
    r = make(tmp_path)
    assert len(r.search("연습", equipment=["골대", "콘", "벽"], k=4)) == 4


def test_index_is_reused_when_documents_are_unchanged(tmp_path):
    emb = FakeEmbeddings()
    make(tmp_path, emb).build()
    calls_after_first_build = emb.calls
    second = make(tmp_path, emb)
    assert second.build() is False  # 다시 만들지 않는다
    assert emb.calls == calls_after_first_build
    assert second.search("레이업", k=1)  # 저장된 색인으로 검색된다


def test_index_is_rebuilt_when_a_document_changes(tmp_path):
    emb = FakeEmbeddings()
    make(tmp_path, emb).build()
    changed = list(DOCS)
    first = changed[0]
    changed[0] = type(first)(**{**first.__dict__, "text": first.text + "\n- 새로 추가한 내용"})
    assert make(tmp_path, emb, docs=changed).build() is True


def test_rebuild_flag_forces_a_new_index(tmp_path):
    r = make(tmp_path)
    r.build()
    assert make(tmp_path).build(rebuild=True) is True
