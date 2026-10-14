"""The search entry point: dense-only, BM25-only, or hybrid (RRF-fused), with optional HyDE
query rewriting, cross-encoder reranking, context deduplication, and context compression —
the full Hybrid RAG pipeline from Section 8.A, composable via flags since Phase 6's agentic
mode and Phase 8's benchmark matrix both need to turn individual stages on and off.

Every embed/rerank/compress call below is genuinely synchronous, CPU/GPU-bound local inference
(sentence-transformers / a cross-encoder), not an awaited network call — and this function runs
on every single chat turn (via app/agents/tools.py's hybrid_search_tool). Each one is wrapped in
`asyncio.to_thread` (Fix 1 — see docs/DECISIONS.md): left unwrapped, each call blocks the one
shared asyncio event loop for the whole forward pass, stalling every other concurrent
coroutine on the process — other users' chat requests, health checks, the trace WebSocket — for
as long as that call takes. The codebase already uses this exact pattern correctly for
ingestion-time embedding (app/retrieval/indexing.py) and startup warm-up
(app/core/preflight.py); it just was never applied to this, the actual per-request hot path.
"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from typing import Any

from app.embeddings.registry import get_embedder
from app.retrieval.compression import compress_hits
from app.retrieval.dedupe import cosine_threshold_dedupe, mmr_select, ngram_overlap_dedupe
from app.retrieval.hybrid import FusedHit, reciprocal_rank_fusion
from app.retrieval.hyde import hyde_rewrite
from app.retrieval.reranker import get_reranker
from app.stores.bm25 import get_bm25_index
from app.stores.vector import get_vector_store

VALID_MODES = ("hybrid", "dense", "bm25")
VALID_DEDUPE_STRATEGIES = ("mmr", "cosine", "ngram")

# Every search made while a collector is active appends its own funnel here: how many
# candidates each step saw. A mutable list in a ContextVar, so searches made deep inside the
# agent graph are still counted without threading an argument through every node.
_funnels: ContextVar[list[dict[str, Any]] | None] = ContextVar("_retrieval_funnels", default=None)


def start_funnel_collection() -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    _funnels.set(collected)
    return collected


def stop_funnel_collection() -> None:
    _funnels.set(None)


async def search(
    query: str,
    k: int = 5,
    doc_id: str | None = None,
    mode: str = "hybrid",
    use_hyde: bool = False,
    rerank: bool = False,
    dedupe_strategy: str | None = None,
    compress: bool = False,
    max_context_tokens: int = 1000,
    variant: str = "default",
) -> list[FusedHit]:
    """`variant` selects which chunking of the document to search: the working index
    ("default") or an alternative one built for a strategy (app/rag_engines/variants.py)."""
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown search mode: {mode!r}. Valid: {VALID_MODES}")
    if dedupe_strategy is not None and dedupe_strategy not in VALID_DEDUPE_STRATEGIES:
        raise ValueError(
            f"Unknown dedupe strategy: {dedupe_strategy!r}. Valid: {VALID_DEDUPE_STRATEGIES}"
        )

    search_query = await hyde_rewrite(query) if use_hyde else query

    is_variant = variant != "default"
    where: dict[str, Any] | None = {"doc_id": doc_id} if doc_id else None
    if is_variant:
        clauses: list[dict[str, Any]] = [{"variant": variant}]
        if doc_id:
            clauses.append({"doc_id": doc_id})
        where = clauses[0] if len(clauses) == 1 else {"$and": clauses}
    vector_store = get_vector_store(variants=is_variant)
    over_fetch = rerank or dedupe_strategy is not None
    fetch_k = max(k * 4, 20) if over_fetch else max(k * 3, 10)

    dense_hits = []
    bm25_hits = []
    if mode in ("hybrid", "dense"):
        query_emb = await asyncio.to_thread(get_embedder().embed_one, search_query)
        dense_hits = vector_store.query(query_emb, k=fetch_k, where=where)
    if mode in ("hybrid", "bm25"):
        bm25_hits = get_bm25_index().search(search_query, k=fetch_k, doc_id=doc_id, variant=variant)

    if mode == "dense":
        candidates = [
            FusedHit(
                chunk_id=h.chunk_id,
                score=h.score,
                text=h.text,
                dense_rank=i + 1,
                dense_score=h.score,
            )
            for i, h in enumerate(dense_hits)
        ]
    elif mode == "bm25":
        candidates = [
            FusedHit(
                chunk_id=h.chunk_id, score=h.score, text=h.text, bm25_rank=i + 1, bm25_score=h.score
            )
            for i, h in enumerate(bm25_hits)
        ]
    else:
        candidates = reciprocal_rank_fusion(dense_hits, bm25_hits, k=fetch_k)

    funnel: dict[str, Any] = {
        "mode": mode,
        "variant": variant,
        "hyde": use_hyde,
        "dense_candidates": len(dense_hits),
        "sparse_candidates": len(bm25_hits),
        "after_fusion": len(candidates),
    }

    if rerank:
        # Reranked against the *original* query — HyDE is a retrieval trick, not a redefinition
        # of what counts as relevant for the final answer.
        candidates = await asyncio.to_thread(get_reranker().rerank, query, candidates)
        funnel["after_rerank"] = len(candidates)

    if dedupe_strategy == "mmr":
        query_emb = await asyncio.to_thread(get_embedder().embed_one, query)
        embeddings = vector_store.get_embeddings([h.chunk_id for h in candidates])
        candidates = mmr_select(query_emb, candidates, embeddings, k=k)
    elif dedupe_strategy == "cosine":
        embeddings = vector_store.get_embeddings([h.chunk_id for h in candidates])
        candidates = cosine_threshold_dedupe(candidates, embeddings)
    elif dedupe_strategy == "ngram":
        candidates = ngram_overlap_dedupe(candidates)

    if dedupe_strategy is not None:
        funnel["after_dedupe"] = len(candidates)

    candidates = candidates[:k]
    funnel["returned"] = len(candidates)
    collector = _funnels.get()
    if collector is not None:
        collector.append(funnel)

    if compress:
        candidates = await asyncio.to_thread(
            compress_hits, query, candidates, max_tokens=max_context_tokens
        )

    return candidates
