"""연습 메뉴 문서 검색 (RAG).

data/menus/*.md 문서를 임베딩해 Chroma에 색인하고, 질의와 비슷한 문서를 찾는다.
- 임베딩: Bedrock Titan Text Embeddings v2 (한국어 지원). 모델은 .env의 EMBEDDING_MODEL_ID로 바꿀 수 있다.
- 색인은 chroma_db/menus에 저장하고, 문서나 임베딩 모델이 바뀌면 다음 실행에서 자동으로 다시 만든다.
- 검색 결과는 사용자가 가진 장소·장비로 할 수 있는 메뉴(와 원하면 난이도)만 남긴다.
"""
import hashlib
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from src.tracing import traced

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
MENUS_DIR = ROOT / "data" / "menus"
GUIDES_DIR = ROOT / "data" / "guides"
INDEX_DIR = ROOT / "chroma_db" / "menus"
DEFAULT_EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
COLLECTION = "menus"


@dataclass(frozen=True)
class MenuDoc:
    """검색 대상 문서. kind가 "menu"이면 연습 메뉴 문서, "guide"이면 용어·원리·규칙 같은 안내 문서다.

    안내 문서에는 난이도·장비·슛 여부가 없다 (difficulty는 빈 문자열, requires는 빈 튜플)."""

    doc_id: str
    name: str
    difficulty: str
    requires: tuple[str, ...]
    is_shooting: bool
    text: str  # 머리말을 뺀 문서 본문. 임베딩과 API 응답의 contexts에 쓴다.
    kind: str = "menu"


@dataclass(frozen=True)
class SearchResult:
    doc: MenuDoc
    distance: float  # 코사인 거리. 작을수록 질의와 비슷하다.


def parse_menu_doc(path: Path) -> MenuDoc:
    raw = path.read_text(encoding="utf-8")
    head, body = raw[4:].split("\n---\n", 1)
    meta = dict(line.split(": ", 1) for line in head.splitlines())
    kind = meta.get("kind", "menu")
    requires = () if meta.get("requires", "없음") == "없음" else tuple(meta["requires"].split(", "))
    return MenuDoc(
        doc_id=meta["doc_id"],
        name=meta["name"],
        difficulty=meta.get("difficulty", ""),
        requires=requires,
        is_shooting=meta.get("is_shooting") == "true",
        text=body.strip(),
        kind=kind,
    )


def load_menu_docs(directory: Path = MENUS_DIR) -> list[MenuDoc]:
    return [parse_menu_doc(p) for p in sorted(directory.glob("*.md"))]


def load_guide_docs(directory: Path = GUIDES_DIR) -> list[MenuDoc]:
    return [parse_menu_doc(p) for p in sorted(directory.glob("*.md"))]


def load_all_docs() -> list[MenuDoc]:
    """연습 메뉴 문서와 안내 문서를 모두 읽는다."""
    return load_menu_docs() + load_guide_docs()


def get_embeddings() -> Embeddings:
    from langchain_aws import BedrockEmbeddings

    return BedrockEmbeddings(
        model_id=os.getenv("EMBEDDING_MODEL_ID", DEFAULT_EMBEDDING_MODEL_ID),
        region_name=os.getenv("AWS_DEFAULT_REGION"),
    )


class MenuRetriever:
    def __init__(
        self,
        docs: list[MenuDoc] | None = None,
        embeddings: Embeddings | None = None,
        index_dir: Path = INDEX_DIR,
        model_id: str | None = None,
    ):
        self.docs = docs if docs is not None else load_all_docs()
        self._by_id = {d.doc_id: d for d in self.docs}
        self._embeddings = embeddings
        self.index_dir = Path(index_dir)
        self.model_id = model_id or os.getenv("EMBEDDING_MODEL_ID", DEFAULT_EMBEDDING_MODEL_ID)
        self._store: Chroma | None = None

    # -- 색인 ---------------------------------------------------------------
    def _fingerprint(self) -> str:
        h = hashlib.sha256(self.model_id.encode("utf-8"))
        for d in self.docs:
            h.update(f"{d.doc_id}\0{d.text}\0".encode("utf-8"))
        return h.hexdigest()

    @property
    def _fingerprint_file(self) -> Path:
        return self.index_dir / "fingerprint.txt"

    def _open(self) -> Chroma:
        return Chroma(
            collection_name=COLLECTION,
            embedding_function=self._embeddings or get_embeddings(),
            persist_directory=str(self.index_dir),
            collection_metadata={"hnsw:space": "cosine"},
        )

    def build(self, rebuild: bool = False) -> bool:
        """색인을 준비한다. 문서·모델이 그대로면 기존 색인을 쓰고, 달라졌거나 rebuild면 다시 만든다. 다시 만들었으면 True."""
        current = self._fingerprint()
        up_to_date = (
            self._fingerprint_file.exists() and self._fingerprint_file.read_text(encoding="utf-8") == current
        )
        if up_to_date and not rebuild:
            self._store = self._open()
            return False
        if self.index_dir.exists():
            shutil.rmtree(self.index_dir, ignore_errors=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._store = self._open()
        self._store.add_documents(
            [
                Document(
                    page_content=d.text,
                    metadata={"doc_id": d.doc_id},
                    id=d.doc_id,
                )
                for d in self.docs
            ]
        )
        self._fingerprint_file.write_text(current, encoding="utf-8")
        return True

    # -- 검색 ---------------------------------------------------------------
    def search(
        self,
        query: str,
        equipment: list[str] | None = None,
        levels: list[str] | None = None,
        k: int = 5,
        kinds: list[str] | None = None,
        max_distance: float | None = None,
    ) -> list[SearchResult]:
        """질의와 비슷한 문서를 찾는다.

        equipment를 주면 그 장소·장비로 할 수 있는 메뉴만, levels를 주면 그 난이도 메뉴만 남긴다. (안내 문서에는 적용하지 않는다.)
        kinds를 주면 그 종류("menu", "guide")의 문서만, max_distance를 주면 그보다 먼 문서는 뺀다.
        """
        if self._store is None:
            self.build()
        assert self._store is not None
        hits = self._store.similarity_search_with_score(query, k=len(self.docs))
        owned = None if equipment is None else set(equipment)
        results: list[SearchResult] = []
        for document, distance in hits:
            doc = self._by_id[document.metadata["doc_id"]]
            if kinds is not None and doc.kind not in kinds:
                continue
            if max_distance is not None and distance > max_distance:
                continue
            if doc.kind == "menu":
                if owned is not None and not set(doc.requires) <= owned:
                    continue
                if levels is not None and doc.difficulty not in levels:
                    continue
            results.append(SearchResult(doc, float(distance)))
            if len(results) == k:
                break
        return results

    # -- 하이브리드 검색 (용어 일치 + 의미 검색) ----------------------------------
    def match_terms(self, query: str) -> list[MenuDoc]:
        """질문에 '- 용어: 설명' 형식의 용어가 그대로 들어 있는 안내 문서를 찾는다. (공백은 무시하고 비교)"""
        flat = query.replace(" ", "")
        hits: list[MenuDoc] = []
        for doc in self.docs:
            if doc.kind != "guide":
                continue
            terms = re.findall(r"^- ([^:]{2,20}):", doc.text, re.M)
            if any(t.replace(" ", "") in flat for t in terms):
                hits.append(doc)
        return hits

    @traced("retrieve", "retriever", keep=("query", "k", "max_distance", "kinds"))
    def search_hybrid(
        self,
        query: str,
        k: int = 3,
        max_distance: float | None = None,
        margin: float | None = None,
        kinds: list[str] | None = None,
    ) -> list[SearchResult]:
        """용어가 질문에 그대로 있는 안내 문서(distance 0.0)를 먼저, 이어서 의미가 비슷한 문서를 돌려준다.

        max_distance보다 먼 문서는 빼고, margin을 주면 가장 가까운 의미 검색 결과보다 margin 넘게 먼 문서도 뺀다.
        """
        results = [SearchResult(d, 0.0) for d in self.match_terms(query) if kinds is None or d.kind in kinds]
        semantic = self.search(query, k=k + len(results), kinds=kinds, max_distance=max_distance)
        if margin is not None and semantic:
            best = semantic[0].distance
            semantic = [r for r in semantic if r.distance <= best + margin]
        seen = {r.doc.doc_id for r in results}
        results += [r for r in semantic if r.doc.doc_id not in seen]
        return results[:k]
