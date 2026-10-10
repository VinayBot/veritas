"""Semantic cache: a repeat or near-identical question is answered from cache — guardrails
still run on the way out, and the cache hit is a real, visible trace event, not a silent
shortcut.

In-memory, scoped by (doc_id, mode) so a cached hybrid-mode answer is never reused for
graph-mode. `REDIS_URL` exists in settings for a future Redis-backed version (bigger-than-one-
process deployments) — not built, since nothing in this project runs more than one backend
process; documented as a known scaling placeholder rather than quietly ignored.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.embeddings.registry import get_embedder

SIMILARITY_THRESHOLD = 0.96
MAX_ENTRIES = 500


@dataclass
class CacheEntry:
    query: str
    embedding: np.ndarray
    doc_id: str | None
    mode: str
    answer: str
    citations: Sequence[Mapping[str, Any]]
    created_at: float = field(default_factory=time.time)


_cache: list[CacheEntry] = []


def _scope_matches(entry: CacheEntry, doc_id: str | None, mode: str) -> bool:
    return entry.doc_id == doc_id and entry.mode == mode


async def lookup(query: str, doc_id: str | None, mode: str) -> CacheEntry | None:
    if not get_settings().semantic_cache_enabled or not _cache:
        return None
    query_emb = get_embedder().embed_one(query)
    best: CacheEntry | None = None
    best_sim = -1.0
    for entry in _cache:
        if not _scope_matches(entry, doc_id, mode):
            continue
        sim = float(np.dot(query_emb, entry.embedding))
        if sim > best_sim:
            best_sim, best = sim, entry
    return best if best is not None and best_sim >= SIMILARITY_THRESHOLD else None


async def store(
    query: str, doc_id: str | None, mode: str, answer: str, citations: Sequence[Mapping[str, Any]]
) -> None:
    if not get_settings().semantic_cache_enabled:
        return
    query_emb = get_embedder().embed_one(query)
    _cache.append(
        CacheEntry(
            query=query,
            embedding=query_emb,
            doc_id=doc_id,
            mode=mode,
            answer=answer,
            citations=citations,
        )
    )
    if len(_cache) > MAX_ENTRIES:
        del _cache[: len(_cache) - MAX_ENTRIES]


def clear() -> None:
    _cache.clear()


def size() -> int:
    return len(_cache)
