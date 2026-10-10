"""Reciprocal Rank Fusion over dense (Chroma) and BM25 result lists, with an optional weighted
alpha (default: equal weight)."""

from __future__ import annotations

from pydantic import BaseModel

from app.stores.bm25 import Bm25Hit
from app.stores.vector.base import VectorHit

RRF_K = 60


class FusedHit(BaseModel):
    chunk_id: str
    score: float
    text: str
    dense_rank: int | None = None
    bm25_rank: int | None = None
    dense_score: float | None = None
    bm25_score: float | None = None
    rerank_score: float | None = None


def reciprocal_rank_fusion(
    dense_hits: list[VectorHit],
    bm25_hits: list[Bm25Hit],
    k: int,
    alpha: float = 0.5,
    rrf_k: int = RRF_K,
) -> list[FusedHit]:
    dense_rank = {h.chunk_id: i + 1 for i, h in enumerate(dense_hits)}
    bm25_rank = {h.chunk_id: i + 1 for i, h in enumerate(bm25_hits)}
    dense_by_id = {h.chunk_id: h for h in dense_hits}
    bm25_by_id = {h.chunk_id: h for h in bm25_hits}

    all_ids = set(dense_rank) | set(bm25_rank)
    fused: list[FusedHit] = []
    for chunk_id in all_ids:
        d_rank = dense_rank.get(chunk_id)
        b_rank = bm25_rank.get(chunk_id)
        score = 0.0
        if d_rank is not None:
            score += alpha * (1.0 / (rrf_k + d_rank))
        if b_rank is not None:
            score += (1.0 - alpha) * (1.0 / (rrf_k + b_rank))

        text = dense_by_id[chunk_id].text if chunk_id in dense_by_id else bm25_by_id[chunk_id].text
        fused.append(
            FusedHit(
                chunk_id=chunk_id,
                score=score,
                text=text,
                dense_rank=d_rank,
                bm25_rank=b_rank,
                dense_score=dense_by_id[chunk_id].score if chunk_id in dense_by_id else None,
                bm25_score=bm25_by_id[chunk_id].score if chunk_id in bm25_by_id else None,
            )
        )
    fused.sort(key=lambda h: h.score, reverse=True)
    return fused[:k]
