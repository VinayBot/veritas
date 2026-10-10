from __future__ import annotations

from conftest import wait_for_document, wait_for_enrichment
from httpx import AsyncClient

from app.agents.tools import graph_traverse_tool, hybrid_search_tool, pii_vault_lookup_tool


async def test_hybrid_search_tool_finds_relevant_chunk(client: AsyncClient) -> None:
    files = {
        "file": (
            "policy.md",
            b"# Vacation\n\nEmployees get two paid vacation days per month of service.",
            "text/markdown",
        )
    }
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]
    await wait_for_document(client, document_id)

    hits = await hybrid_search_tool("How much vacation do employees get?", document_id, k=3)
    assert hits
    assert any("vacation" in h["text"].lower() for h in hits)
    assert all(h["source"] == "hybrid" for h in hits)


async def test_graph_traverse_tool_returns_evidence_or_empty(client: AsyncClient) -> None:
    files = {
        "file": (
            "about.md",
            b"Nightsong Robotics partnered with Fogglass Analytics on a new project.",
            "text/markdown",
        )
    }
    upload = await client.post("/api/v1/documents/upload", files=files)
    await wait_for_enrichment(client, upload.json()["document_id"])

    hits = await graph_traverse_tool("Nightsong Robotics")
    # Either real chunk evidence or a synthesized path description — never raises, and if it
    # does find something, it's tagged "graph" (not silently mixed in with hybrid results).
    assert all(h["source"] == "graph" for h in hits)


async def test_pii_vault_lookup_tool_denied_without_reveal() -> None:
    hits = await pii_vault_lookup_tool("what is jane@example.com's number", "s1", reveal_pii=False)
    assert len(hits) == 1
    assert "Reveal PII" in hits[0]["text"]


async def test_pii_vault_lookup_tool_reveals_known_value(client: AsyncClient) -> None:
    files = {"file": ("letter.txt", b"Contact jane.tools@example.com for details.", "text/plain")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    await wait_for_document(client, upload.json()["document_id"])

    hits = await pii_vault_lookup_tool(
        "What is jane.tools@example.com's record?", "s1", reveal_pii=True
    )
    assert any("jane.tools@example.com" in h["text"] for h in hits)


async def test_pii_vault_lookup_tool_no_pii_in_query_returns_empty() -> None:
    hits = await pii_vault_lookup_tool("what is the vacation policy", "s1", reveal_pii=True)
    assert hits == []
