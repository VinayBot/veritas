from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.guardrails import rate_limit


@pytest.fixture(autouse=True)
def _clear():
    rate_limit.clear()
    yield
    rate_limit.clear()


def test_allows_requests_under_the_limit() -> None:
    session_id = "s1"
    limit = get_settings().rate_limit_per_minute
    for _ in range(limit):
        assert rate_limit.check(session_id) is True


def test_blocks_requests_over_the_limit() -> None:
    session_id = "s2"
    limit = get_settings().rate_limit_per_minute
    for _ in range(limit):
        rate_limit.check(session_id)
    assert rate_limit.check(session_id) is False


def test_sessions_are_independent() -> None:
    limit = get_settings().rate_limit_per_minute
    for _ in range(limit):
        rate_limit.check("session-a")
    assert rate_limit.check("session-a") is False
    assert rate_limit.check("session-b") is True


async def test_a_client_cannot_dodge_the_limit_by_changing_session(client, monkeypatch) -> None:
    """The per-client limit counts requests from one address whatever session they name;
    beyond it the API answers 429 with Retry-After, before any model work starts."""
    monkeypatch.setattr(get_settings(), "client_rate_limit_per_minute", 3)
    statuses = []
    for i in range(3):
        # Not limited: an estimate starts no model work.
        await client.post("/api/v1/rag/compare/estimate", json={"document_id": f"d{i}"})
        # Limited: the check runs before the handler, which then finds no such document.
        resp = await client.post(f"/api/v1/documents/missing-{i}/measure")
        statuses.append(resp.status_code)
    assert 429 not in statuses
    limited = await client.post("/api/v1/documents/missing-3/measure")
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert limited.json()["code"] == "rate_limited"
    # A different scope has its own budget.
    other = await client.post("/api/v1/eval/benchmarks/start", json={})
    assert other.status_code == 422  # reached validation: not rate limited


def test_counters_are_per_scope_and_key() -> None:
    counter = rate_limit.MemoryCounter()
    assert all(counter.hit("client:chat:1.2.3.4", 2) for _ in range(2))
    assert counter.hit("client:chat:1.2.3.4", 2) is False
    assert counter.hit("client:upload:1.2.3.4", 2) is True
    assert counter.hit("client:chat:5.6.7.8", 2) is True


def test_a_redis_outage_falls_back_to_memory_instead_of_refusing() -> None:
    redis = pytest.importorskip("redis")
    assert redis
    counter = rate_limit.RedisCounter("redis://127.0.0.1:1/0")  # nothing listens there
    assert counter.hit("k", 1) is True
    assert counter.hit("k", 1) is False


def test_redis_counts_are_shared_between_counters() -> None:
    """Two counters on one Redis act as two backend processes would. Runs where REDIS_URL
    points at a server (CI starts one), skipped otherwise."""
    import os

    url = os.environ.get("REDIS_URL")
    if not url:
        pytest.skip("REDIS_URL is not set; no Redis server to test against")
    first, second = rate_limit.RedisCounter(url), rate_limit.RedisCounter(url)
    first.clear()
    assert first.hit("shared", 2) and second.hit("shared", 2)
    assert first.hit("shared", 2) is False and second.hit("shared", 2) is False
    first.clear()
