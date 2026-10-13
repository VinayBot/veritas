from __future__ import annotations

from conftest import wait_for_enrichment
from httpx import AsyncClient


async def test_upload_builds_graph_and_graph_endpoint_returns_it(client: AsyncClient) -> None:
    # Org/location names (not person names) deliberately — PERSON is masked by the PII vault
    # before GraphRAG ever sees the text (correct, required behavior: raw PII must never reach
    # the graph), so a test asserting specific *person* names survive would be testing the PII
    # vault's redaction, not GraphRAG. See docs/DECISIONS.md for the full finding.
    content = (
        b"# About Us\n\n"
        b"Quasarmind Robotics was founded in the city of Ferrowick. "
        b"Quasarmind Robotics later partnered with Driftglass Logistics on a joint research "
        b"program based in Ferrowick."
    )
    files = {"file": ("about.md", content, "text/markdown")}
    upload_resp = await client.post("/api/v1/documents/upload", files=files)
    assert upload_resp.status_code == 200
    document_id = upload_resp.json()["document_id"]

    body = await wait_for_enrichment(client, document_id)
    assert body["enrichment_status"] == "done", body.get("enrichment_error")
    assert body["graph_entity_count"] is not None
    assert body["graph_entity_count"] >= 1

    graph_resp = await client.get(f"/api/v1/graph/{document_id}")
    assert graph_resp.status_code == 200
    graph = graph_resp.json()
    assert graph["nodes"]
    names = {n["name"] for n in graph["nodes"]}
    assert any("Quasarmind" in n or "Driftglass" in n or "Ferrowick" in n for n in names)


async def test_graph_endpoint_with_query_links_entities(client: AsyncClient) -> None:
    content = b"Blackridge Mining signed a contract with Silverpine Logistics in Haversham."
    files = {"file": ("contract.txt", content, "text/plain")}
    upload_resp = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload_resp.json()["document_id"]
    await wait_for_enrichment(client, document_id)

    # Adaptive on purpose: PII masking is context-sensitive (the exact same name can survive or
    # be redacted depending on surrounding text — see docs/DECISIONS.md), so rather than assume
    # a specific name survives, ask the graph what it actually has and query with that.
    unqueried = await client.get(f"/api/v1/graph/{document_id}")
    nodes = unqueried.json()["nodes"]
    assert nodes, "expected at least one real (non-PII) entity to survive in this fixture"
    probe_name = nodes[0]["name"]

    # The whole name, not a prefix: the store is shared with every other document in the
    # corpus, and an 8-character prefix can link to a different document's entity first.
    graph_resp = await client.get(f"/api/v1/graph/{document_id}", params={"query": probe_name})
    assert graph_resp.status_code == 200
    graph = graph_resp.json()
    assert graph["linked_entities"]
    assert any(n["id"] == nodes[0]["id"] for n in graph["linked_entities"])


async def test_graph_query_is_scoped_to_the_document_and_empty_when_nothing_matches(
    client: AsyncClient,
) -> None:
    """A filter that matches nothing returns nothing (it used to fall back to the whole
    graph), and a name that only exists in another document does not link."""
    one = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("a.txt", b"Quillhaven Robotics acquired Dunmere Optics.", "text/plain")},
    )
    two = await client.post(
        "/api/v1/documents/upload",
        files={"file": ("b.txt", b"Larkspur Freight opened a depot in Westmarch.", "text/plain")},
    )
    first, second = one.json()["document_id"], two.json()["document_id"]
    await wait_for_enrichment(client, first)
    await wait_for_enrichment(client, second)

    nonsense = (await client.get(f"/api/v1/graph/{first}", params={"query": "qxqxqxqxqx"})).json()
    assert nonsense["nodes"] == [] and nonsense["edges"] == []

    other = (
        await client.get(f"/api/v1/graph/{first}", params={"query": "Larkspur Freight"})
    ).json()
    assert other["nodes"] == [] and not other["linked_entities"]

    # Which names survive PII masking depends on context, so ask the graph what it holds.
    nodes = (await client.get(f"/api/v1/graph/{first}")).json()["nodes"]
    assert nodes
    own = (await client.get(f"/api/v1/graph/{first}", params={"query": nodes[0]["name"]})).json()
    assert any(n["id"] == nodes[0]["id"] for n in own["linked_entities"])
    assert all(first in n["doc_ids"] for n in own["nodes"])
