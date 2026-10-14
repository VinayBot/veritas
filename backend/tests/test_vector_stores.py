"""Both vector stores behind one interface: the same data gives the same hits, in the same
order, with the same [0, 1] scores, and filters and deletes behave alike."""

from __future__ import annotations

import numpy as np
import pytest

qdrant_client = pytest.importorskip("qdrant_client")

from app.stores.vector.chroma_store import ChromaVectorStore  # noqa: E402
from app.stores.vector.qdrant_store import QdrantVectorStore, to_qdrant_filter  # noqa: E402

DIM = 8


def _unit(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=DIM)
    return v / np.linalg.norm(v)


IDS = [f"chunk-{i}" for i in range(6)]
VECTORS = np.stack([_unit(i) for i in range(6)])
DOCS = [f"text {i}" for i in range(6)]
METAS = [{"doc_id": "a" if i < 3 else "b", "variant": "default"} for i in range(6)]


@pytest.fixture
def stores(tmp_path):
    import chromadb

    chroma = ChromaVectorStore(chromadb.PersistentClient(path=str(tmp_path / "c")), "chunks")
    qdrant = QdrantVectorStore(qdrant_client.QdrantClient(path=str(tmp_path / "q")), "chunks")
    for store in (chroma, qdrant):
        store.add(IDS, VECTORS, DOCS, METAS)
    return chroma, qdrant


def test_same_hits_and_scores_from_both_stores(stores):
    chroma, qdrant = stores
    query = _unit(2) + 0.1 * _unit(99)
    a = chroma.query(query, k=4)
    b = qdrant.query(query, k=4)
    assert [h.chunk_id for h in a] == [h.chunk_id for h in b]
    assert a[0].chunk_id == "chunk-2"
    for x, y in zip(a, b, strict=True):
        assert x.score == pytest.approx(y.score, abs=1e-4)
        assert 0.0 <= y.score <= 1.0
        assert y.text == x.text and y.metadata["doc_id"] == x.metadata["doc_id"]


def test_filters_and_deletes_match(stores):
    chroma, qdrant = stores
    query = _unit(0)
    where = {"$and": [{"doc_id": "b"}, {"variant": "default"}]}
    assert {h.chunk_id for h in qdrant.query(query, 6, where)} == {"chunk-3", "chunk-4", "chunk-5"}
    assert {h.chunk_id for h in qdrant.query(query, 6, where)} == {
        h.chunk_id for h in chroma.query(query, 6, where)
    }
    for store in stores:
        store.delete_by_doc("a")
        assert store.count() == 3


def test_stored_vectors_come_back_by_chunk_id(stores):
    _, qdrant = stores
    got = qdrant.get_embeddings(["chunk-1", "chunk-4"])
    assert set(got) == {"chunk-1", "chunk-4"}
    np.testing.assert_allclose(got["chunk-1"], VECTORS[1], atol=1e-5)


def test_unsupported_filters_are_refused():
    with pytest.raises(ValueError):
        to_qdrant_filter({"doc_id": {"$in": ["a", "b"]}})
    assert to_qdrant_filter(None) is None
