from __future__ import annotations

import json

import pytest
from conftest import upload_and_wait_ready, wait_for_enrichment
from httpx import AsyncClient

DOC = (
    b"# Partnership\n\nEmberwood Studios collaborated with Hollowpine Games on a title called "
    b"Lanternfall. Hollowpine Games is based in Reykjavik. Emberwood Studios was founded by "
    b"Mara Quill in 2011.\n"
)


@pytest.mark.needs_ollama
async def test_overview_is_computed_from_real_rows(client: AsyncClient) -> None:
    doc = await upload_and_wait_ready(client, "partners.md", DOC, "text/markdown")
    before = (await client.get("/api/v1/analytics/overview")).json()

    chat = await client.post(
        "/api/v1/chat",
        json={
            "message": "Who founded Emberwood Studios?",
            "document_id": doc["id"],
            "strategy": "hybrid",
        },
    )
    done = json.loads(
        next(b for b in chat.text.split("\n\n") if b.startswith("event: done")).split("data: ")[1]
    )
    report = (await client.get(f"/api/v1/reports/{done['report_id']}")).json()

    after = (await client.get("/api/v1/analytics/overview")).json()
    assert after["queries"]["in_window"] == before["queries"]["in_window"] + 1
    assert after["queries"]["all_time"] == before["queries"]["all_time"] + 1
    assert after["corpus"]["documents"] >= 1
    assert after["corpus"]["chunks"] >= doc["chunk_count"]
    assert after["corpus"]["tokens"] > 0
    assert after["corpus"]["index_bytes"]["vectors"] > 0
    assert after["corpus"]["last_ingest"]["filename"]

    mix = {m["strategy"]: m for m in after["queries"]["strategy_mix"]}
    assert mix["hybrid"]["count"] >= 1
    assert abs(sum(m["share"] for m in mix.values()) - 1.0) < 1e-9
    stages = {s["stage"]: s for s in after["queries"]["latency_by_stage"]}
    assert {"retriever", "synthesizer"} <= set(stages)
    assert all(s["n"] >= 1 and s["p95"] >= s["p50"] for s in stages.values())
    assert after["queries"]["latency_ms"]["n"] >= 1
    assert after["queries"]["reports_with_token_counts"] >= 1

    today = after["queries"]["by_day"][-1]
    assert today["queries"] >= 1
    expected_zero = 0 if report["citations"] else 1
    assert (
        after["quality"]["zero_citation_answers"]
        >= before["quality"]["zero_citation_answers"] + expected_zero
    )
    assert after["quality"]["avg_citations"] is not None
    assert after["reliability"]["runs"] == before["reliability"]["runs"] + 1
    assert after["guardrails"]["total"] > before["guardrails"]["total"]


async def test_overview_on_a_window_with_no_traffic_reports_nothing_rather_than_zeros(
    client: AsyncClient,
) -> None:
    body = (await client.get("/api/v1/analytics/overview", params={"days": 1})).json()
    assert body["window_days"] == 1
    # Shares and rates are None when there is nothing to divide by.
    if body["queries"]["in_window"] == 0:
        assert body["quality"]["faithfulness"] is None
        assert body["quality"]["zero_citation_rate"] is None
        assert body["queries"]["latency_ms"]["p50"] is None


async def test_graph_stats_describe_the_real_graph(client: AsyncClient) -> None:
    doc = await upload_and_wait_ready(client, "partners.md", DOC, "text/markdown")
    enriched = await wait_for_enrichment(client, doc["id"])

    stats = (await client.get("/api/v1/graph/stats", params={"document_id": doc["id"]})).json()
    graph = (await client.get(f"/api/v1/graph/{doc['id']}")).json()
    assert stats["entities"] == len(graph["nodes"])
    assert stats["relations"] == len(graph["edges"])
    assert stats["entities"] > 0 and enriched["graph_entity_count"] > 0
    connected = {e["source"] for e in graph["edges"]} | {e["target"] for e in graph["edges"]}
    assert stats["orphans"] == len([n for n in graph["nodes"] if n["id"] not in connected])
    assert stats["orphan_rate"] == stats["orphans"] / stats["entities"]
    for entity in stats["most_connected"]:
        assert entity["degree"] >= 1 and entity["name"]
    assert sum(c["size"] for c in stats["largest_communities"]) <= stats["entities"]

    corpus = (await client.get("/api/v1/graph/stats")).json()
    assert corpus["entities"] >= stats["entities"]
    overview = (await client.get("/api/v1/graph", params={"limit": 5})).json()
    assert len(overview["nodes"]) <= 5
    ids = {n["id"] for n in overview["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in overview["edges"])
