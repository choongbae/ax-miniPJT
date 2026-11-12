"""테스트 공용 도구: 실제 임베딩 대신 쓰는 결정적 가짜 임베딩과 이를 쓰는 검색기."""
import hashlib
import math
import os

import pytest
from langchain_core.embeddings import Embeddings

os.environ["LANGSMITH_TRACING"] = "false"  # 테스트는 외부로 트레이스를 보내지 않는다 (src를 불러오기 전에 정한다)

from src.retriever import MenuRetriever, load_all_docs


class FakeEmbeddings(Embeddings):
    """같은 글자(2글자 조각)를 많이 공유할수록 가까워지는 결정적 가짜 임베딩."""

    DIM = 256

    def __init__(self):
        self.calls = 0

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.DIM
        t = text.replace(" ", "")
        for i in range(len(t) - 1):
            h = int(hashlib.md5(t[i : i + 2].encode("utf-8")).hexdigest(), 16) % self.DIM
            v[h] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts):
        self.calls += len(texts)
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        self.calls += 1
        return self._vec(text)


@pytest.fixture
def retriever(tmp_path):
    r = MenuRetriever(
        docs=load_all_docs(), embeddings=FakeEmbeddings(), index_dir=tmp_path / "idx", model_id="fake"
    )
    r.build()
    return r
