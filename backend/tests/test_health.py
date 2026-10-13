from __future__ import annotations

import httpx
import pytest
from httpx import AsyncClient

from app.core import health

EXPECTED_SUBSYSTEMS = {
    "ollama",
    "chroma",
    "bm25",
    "graph_store",
    "agent_graph",
    "council",
    "guardrails",
    "trace_ws",
    "embedder",
    "database",
}


async def test_health_ok(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "ollama" in body


async def test_subsystems_reports_every_probe_with_timing(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health/subsystems", params={"force": True})
    assert resp.status_code == 200
    body = resp.json()
    by_id = {s["id"]: s for s in body["subsystems"]}
    assert set(by_id) == EXPECTED_SUBSYSTEMS
    for probe in by_id.values():
        assert probe["status"] in {"healthy", "degraded", "down", "disabled", "not_configured"}
        assert probe["latency_ms"] >= 0
        assert probe["p50_latency_ms"] is not None
        assert probe["checked_at"]
        assert probe["kind"] in {"dependency", "functional", "config"}
    assert by_id["database"]["status"] == "healthy"
    assert by_id["agent_graph"]["raw"]["nodes"]


async def test_ollama_probe_reports_the_real_failure_when_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stopping Ollama must turn its pill red with the actual error, not a generic message."""

    async def refuse() -> dict:
        raise httpx.ConnectError("All connection attempts failed")

    monkeypatch.setattr(health, "ollama_inventory", refuse)
    health.reset_cache()
    results = {r.id: r for r in await health.run_probes(force=True)}
    health.reset_cache()

    assert results["ollama"].status == "down"
    assert "ConnectError" in (results["ollama"].error or "")
    assert "ollama serve" in (results["ollama"].fix or "")
    # Things that depend on Ollama say so; things that do not are unaffected.
    assert results["council"].status == "down"
    assert results["guardrails"].status == "degraded"
    assert results["database"].status == "healthy"


async def test_bm25_probe_flags_an_empty_index_over_a_populated_database(
    client: AsyncClient,
) -> None:
    from conftest import upload_and_wait_ready

    from app.stores.bm25 import get_bm25_index, rebuild_bm25_index

    await upload_and_wait_ready(
        client, "probe.md", b"# Probe\n\nSome real content.", "text/markdown"
    )
    get_bm25_index().rebuild([], [], [])
    try:
        results = {r.id: r for r in await health.run_probes(force=True)}
        assert results["bm25"].status == "degraded"
        assert results["bm25"].raw["chunks_in_database"] > 0
    finally:
        await rebuild_bm25_index()
        health.reset_cache()
    results = {r.id: r for r in await health.run_probes(force=True)}
    assert results["bm25"].status == "healthy"


async def test_probe_results_are_reused_briefly_then_refreshed() -> None:
    health.reset_cache()
    first = await health.run_probes()
    assert await health.run_probes() is first  # served from the short cache
    assert await health.run_probes(force=True) is not first


async def test_self_check_runs_every_stage_and_times_each(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/health/self-check")
    assert resp.status_code == 200
    body = resp.json()
    names = [s["name"] for s in body["stages"]]
    assert names == [
        "database",
        "embed",
        "dense_search",
        "keyword_search",
        "graph",
        "generate",
        "trace",
    ]
    by_name = {s["name"]: s for s in body["stages"]}
    assert by_name["database"]["ok"]
    assert by_name["embed"]["ok"]
    assert "dimension" in by_name["embed"]["detail"]
    assert by_name["trace"]["ok"]
    assert abs(body["total_ms"] - sum(s["duration_ms"] for s in body["stages"])) < 1.0
    assert body["ok"] == all(s["ok"] for s in body["stages"])


async def test_self_check_reports_the_real_generation_failure(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "ollama_base_url", "http://127.0.0.1:9")
    resp = await client.post("/api/v1/health/self-check")
    body = resp.json()
    generate = next(s for s in body["stages"] if s["name"] == "generate")
    assert generate["ok"] is False
    assert generate["error"]
    assert body["ok"] is False
    # Stages that do not need Ollama still pass and are still timed.
    assert next(s for s in body["stages"] if s["name"] == "embed")["ok"]
