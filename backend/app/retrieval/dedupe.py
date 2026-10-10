"""Context deduplication: three different lenses on the same problem (redundant chunks in the
final context), composable rather than mutually exclusive.

MMR and the cosine threshold both need per-chunk embeddings — reused from the vector store
(the exact vectors computed at index time), not recomputed here.
"""

from __future__ import annotations

import numpy as np

from app.retrieval.hybrid import FusedHit


def mmr_select(
    query_embedding: np.ndarray,
    hits: list[FusedHit],
    embeddings: dict[str, np.ndarray],
    k: int,
    lambda_mult: float = 0.5,
) -> list[FusedHit]:
    """Maximal Marginal Relevance: greedily pick the hit that most improves
    `lambda * relevance_to_query - (1 - lambda) * max_similarity_to_already_selected`."""
    candidates = [h for h in hits if h.chunk_id in embeddings]
    remaining = list(candidates)
    selected: list[FusedHit] = []
    selected_embs: list[np.ndarray] = []

    while remaining and len(selected) < k:
        best_idx = 0
        best_score = float("-inf")
        for i, hit in enumerate(remaining):
            emb = embeddings[hit.chunk_id]
            relevance = float(np.dot(query_embedding, emb))
            diversity_penalty = (
                max(float(np.dot(emb, s)) for s in selected_embs) if selected_embs else 0.0
            )
            score = lambda_mult * relevance - (1 - lambda_mult) * diversity_penalty
            if score > best_score:
                best_score, best_idx = score, i
        chosen = remaining.pop(best_idx)
        selected.append(chosen)
        selected_embs.append(embeddings[chosen.chunk_id])

    # Anything missing an embedding (shouldn't normally happen) is appended, unscored, after.
    selected.extend(h for h in hits if h.chunk_id not in embeddings)
    return selected[:k]


def cosine_threshold_dedupe(
    hits: list[FusedHit], embeddings: dict[str, np.ndarray], threshold: float = 0.95
) -> list[FusedHit]:
    """Drop any hit whose embedding is near-identical (>= threshold cosine similarity) to one
    already kept — hits are assumed pre-sorted by relevance, so the first of a near-duplicate
    pair wins."""
    kept: list[FusedHit] = []
    kept_embs: list[np.ndarray] = []
    for hit in hits:
        emb = embeddings.get(hit.chunk_id)
        if emb is None:
            kept.append(hit)
            continue
        if any(float(np.dot(emb, k_emb)) >= threshold for k_emb in kept_embs):
            continue
        kept.append(hit)
        kept_embs.append(emb)
    return kept


def _ngrams(text: str, n: int) -> set[str]:
    words = text.lower().split()
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def ngram_overlap_dedupe(
    hits: list[FusedHit], n: int = 5, threshold: float = 0.7
) -> list[FusedHit]:
    """Catches near-duplicate phrasing a cosine threshold might miss (or might over-trigger on)
    — pure lexical n-gram Jaccard overlap, no embeddings involved."""
    kept: list[FusedHit] = []
    kept_ngrams: list[set[str]] = []
    for hit in hits:
        grams = _ngrams(hit.text, n)
        is_dup = any(
            grams and other and len(grams & other) / min(len(grams), len(other)) >= threshold
            for other in kept_ngrams
        )
        if not is_dup:
            kept.append(hit)
            kept_ngrams.append(grams)
    return kept
