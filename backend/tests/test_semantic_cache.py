from __future__ import annotations

import numpy as np
import pytest

from app.core.config import get_settings
from app.retrieval import semantic_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    semantic_cache.clear()
    yield
    semantic_cache.clear()


async def test_cache_miss_on_empty_cache() -> None:
    result = await semantic_cache.lookup("What is the vacation policy?", "doc-1", "hybrid")
    assert result is None


async def test_cache_hit_on_near_identical_query() -> None:
    await semantic_cache.store(
        "What is the vacation policy?", "doc-1", "hybrid", "Two days per month.", []
    )
    result = await semantic_cache.lookup(
        "What's the vacation policy?",
        "doc-1",
        "hybrid",  # near-identical phrasing
    )
    assert result is not None
    assert result.answer == "Two days per month."


async def test_cache_miss_for_unrelated_query() -> None:
    await semantic_cache.store(
        "What is the vacation policy?", "doc-1", "hybrid", "Two days per month.", []
    )
    result = await semantic_cache.lookup("What is the capital of France?", "doc-1", "hybrid")
    assert result is None


async def test_cache_scoped_by_document_id() -> None:
    await semantic_cache.store(
        "What is the vacation policy?", "doc-1", "hybrid", "Two days per month.", []
    )
    result = await semantic_cache.lookup("What is the vacation policy?", "doc-2", "hybrid")
    assert result is None


async def test_cache_scoped_by_mode() -> None:
    await semantic_cache.store(
        "What is the vacation policy?", "doc-1", "hybrid", "Two days per month.", []
    )
    result = await semantic_cache.lookup("What is the vacation policy?", "doc-1", "graph")
    assert result is None


async def test_cache_evicts_oldest_entry_past_max_entries() -> None:
    # Fill directly to MAX_ENTRIES - 1 with cheap fake entries (real embedding calls for 500
    # entries would make this test slow for no benefit — store()'s own eviction logic is what's
    # under test, not embedding generation) rather than drive it there one real store() at a time.
    fake_embedding = np.zeros(384, dtype=np.float32)
    for i in range(semantic_cache.MAX_ENTRIES - 1):
        semantic_cache._cache.append(
            semantic_cache.CacheEntry(
                query=f"filler question {i}",
                embedding=fake_embedding,
                doc_id="doc-1",
                mode="hybrid",
                answer=f"filler answer {i}",
                citations=[],
            )
        )
    assert semantic_cache.size() == semantic_cache.MAX_ENTRIES - 1

    await semantic_cache.store(
        "What is the vacation policy?", "doc-1", "hybrid", "Two days per month.", []
    )
    assert semantic_cache.size() == semantic_cache.MAX_ENTRIES

    await semantic_cache.store(
        "One more question to push past the cap.", "doc-1", "hybrid", "An answer.", []
    )
    assert semantic_cache.size() == semantic_cache.MAX_ENTRIES
    assert semantic_cache._cache[0].query == "filler question 1"  # entry 0 was evicted


async def test_cache_disabled_never_hits_or_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "semantic_cache_enabled", False)
    await semantic_cache.store(
        "What is the vacation policy?", "doc-1", "hybrid", "Two days per month.", []
    )
    assert semantic_cache.size() == 0

    result = await semantic_cache.lookup("What is the vacation policy?", "doc-1", "hybrid")
    assert result is None
