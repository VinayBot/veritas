from __future__ import annotations

from app.retrieval.hybrid import reciprocal_rank_fusion
from app.stores.bm25 import Bm25Hit
from app.stores.vector.base import VectorHit


def test_rrf_favors_items_ranked_highly_in_both_lists() -> None:
    dense = [
        VectorHit(chunk_id="a", score=0.9, text="a", metadata={}),
        VectorHit(chunk_id="b", score=0.8, text="b", metadata={}),
        VectorHit(chunk_id="c", score=0.7, text="c", metadata={}),
    ]
    bm25 = [
        Bm25Hit(chunk_id="b", score=5.0, text="b"),
        Bm25Hit(chunk_id="c", score=4.0, text="c"),
        Bm25Hit(chunk_id="a", score=3.0, text="a"),
    ]
    fused = reciprocal_rank_fusion(dense, bm25, k=3)
    # "b" is rank 2 in dense and rank 1 in bm25 -> best combined rank.
    assert fused[0].chunk_id == "b"


def test_rrf_includes_items_present_in_only_one_list() -> None:
    dense = [VectorHit(chunk_id="only-dense", score=0.9, text="x", metadata={})]
    bm25 = [Bm25Hit(chunk_id="only-bm25", score=1.0, text="y")]
    fused = reciprocal_rank_fusion(dense, bm25, k=5)
    ids = {h.chunk_id for h in fused}
    assert ids == {"only-dense", "only-bm25"}


def test_rrf_respects_k() -> None:
    dense = [VectorHit(chunk_id=str(i), score=1.0 / i, text="x", metadata={}) for i in range(1, 11)]
    fused = reciprocal_rank_fusion(dense, [], k=3)
    assert len(fused) == 3


def test_bm25_index_rebuild_and_search() -> None:
    from app.stores.bm25 import Bm25Index

    index = Bm25Index()
    assert index.is_empty()
    index.rebuild(
        chunk_ids=["c1", "c2", "c3"],
        texts=[
            "The quick brown fox jumps over the lazy dog",
            "Python is a popular programming language",
            "The lazy dog sleeps all afternoon",
        ],
        doc_ids=["doc-a", "doc-b", "doc-a"],
    )
    assert not index.is_empty()
    hits = index.search("lazy dog", k=5)
    assert hits[0].chunk_id in ("c1", "c3")


def test_bm25_index_filters_by_doc_id() -> None:
    from app.stores.bm25 import Bm25Index

    index = Bm25Index()
    index.rebuild(
        chunk_ids=["c1", "c2"],
        texts=["lazy dog in doc a", "lazy dog in doc b"],
        doc_ids=["doc-a", "doc-b"],
    )
    hits = index.search("lazy dog", k=5, doc_id="doc-b")
    assert all(h.chunk_id == "c2" for h in hits)
