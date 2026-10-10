from __future__ import annotations

import pytest

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
