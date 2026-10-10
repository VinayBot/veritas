from __future__ import annotations

import numpy as np

from app.retrieval.dedupe import cosine_threshold_dedupe, mmr_select, ngram_overlap_dedupe
from app.retrieval.hybrid import FusedHit


def _unit(vec: list[float]) -> np.ndarray:
    arr = np.array(vec, dtype=np.float32)
    return arr / np.linalg.norm(arr)


def test_mmr_prefers_diverse_results_over_near_duplicates() -> None:
    # Chosen numerically (see docs/DECISIONS.md): "b" is a near-duplicate of "a" (very high
    # relevance *and* very high similarity to "a"); "c" is somewhat less relevant but far less
    # similar to "a". At lambda_mult=0.3 (diversity weighted more than relevance), MMR's
    # diversity penalty on "b" outweighs its relevance edge over "c" — this does NOT hold at
    # every lambda (e.g. 0.5 still picks "b"), which is a real property of MMR, not a test bug.
    query_emb = _unit([1.0, 0.0])
    hits = [
        FusedHit(chunk_id="a", score=0.95, text="a"),
        FusedHit(chunk_id="b", score=0.94, text="b"),  # near-duplicate of "a"
        FusedHit(chunk_id="c", score=0.80, text="c"),  # less relevant, but diverse from "a"
    ]
    embeddings = {
        "a": _unit([1.0, 0.05]),
        "b": _unit([1.0, 0.1]),
        "c": _unit([0.9, 0.45]),
    }
    selected = mmr_select(query_emb, hits, embeddings, k=2, lambda_mult=0.3)
    ids = [h.chunk_id for h in selected]
    assert ids[0] == "a"
    assert "c" in ids  # MMR pulls in the diverse one over the near-duplicate "b"


def test_cosine_threshold_dedupe_drops_near_identical_embeddings() -> None:
    hits = [
        FusedHit(chunk_id="a", score=0.9, text="a"),
        FusedHit(chunk_id="b", score=0.8, text="b"),
        FusedHit(chunk_id="c", score=0.7, text="c"),
    ]
    embeddings = {
        "a": _unit([1.0, 0.0]),
        "b": _unit([1.0, 0.001]),  # essentially identical to "a"
        "c": _unit([0.0, 1.0]),
    }
    kept = cosine_threshold_dedupe(hits, embeddings, threshold=0.95)
    ids = {h.chunk_id for h in kept}
    assert ids == {"a", "c"}


def test_ngram_overlap_dedupe_drops_near_identical_text() -> None:
    hits = [
        FusedHit(chunk_id="a", score=0.9, text="The quick brown fox jumps over the lazy dog today"),
        FusedHit(chunk_id="b", score=0.8, text="The quick brown fox jumps over the lazy dog now"),
        FusedHit(chunk_id="c", score=0.7, text="Completely unrelated sentence about astronomy"),
    ]
    kept = ngram_overlap_dedupe(hits, n=4, threshold=0.5)
    ids = [h.chunk_id for h in kept]
    assert "a" in ids
    assert "c" in ids
    assert "b" not in ids


def test_dedupe_functions_handle_empty_input() -> None:
    assert mmr_select(_unit([1.0, 0.0]), [], {}, k=5) == []
    assert cosine_threshold_dedupe([], {}) == []
    assert ngram_overlap_dedupe([]) == []
