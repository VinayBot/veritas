from __future__ import annotations

import asyncio

from conftest import upload_and_wait_ready, wait_for_document, wait_for_enrichment
from httpx import AsyncClient


async def test_upload_txt_document_end_to_end(client: AsyncClient) -> None:
    content = (
        b"Contact our support team at help@example.com or call 212-555-0199.\n"
        b"Contact our support team at help@example.com or call 212-555-0199.\n"
        b"This is a perfectly ordinary sentence with no issues at all in it."
    )
    files = {"file": ("notes.txt", content, "text/plain")}
    resp = await client.post("/api/v1/documents/upload", files=files)
    assert resp.status_code == 200
    document_id = resp.json()["document_id"]

    body = await wait_for_document(client, document_id)
    assert body["status"] == "ready"
    assert body["source_type"] == "upload"
    assert body["pii_counts"].get("EMAIL_ADDRESS", 0) >= 1
    assert body["quality_score_after"] >= body["quality_score_before"]


async def test_get_unknown_document_404s(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/documents/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "document_not_found"
    assert "trace_id" in body


async def test_upload_unsupported_extension_is_rejected(client: AsyncClient) -> None:
    files = {"file": ("virus.exe", b"\x00\x01", "application/octet-stream")}
    resp = await client.post("/api/v1/documents/upload", files=files)
    assert resp.status_code == 422
    assert resp.json()["code"] == "unsupported_format"


async def test_pii_reveal_round_trip(client: AsyncClient) -> None:
    content = b"Email jane.reveal@example.com about the contract."
    files = {"file": ("letter.txt", content, "text/plain")}
    upload_resp = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload_resp.json()["document_id"]

    doc_body = await wait_for_document(client, document_id)
    assert doc_body["pii_counts"]["EMAIL_ADDRESS"] == 1

    from app.privacy.tokenizer import make_token

    token = make_token("EMAIL_ADDRESS", "jane.reveal@example.com")
    reveal_resp = await client.post(
        "/api/v1/pii/reveal", json={"tokens": [token], "session_id": "test-session"}
    )
    assert reveal_resp.status_code == 200
    body = reveal_resp.json()
    assert body["revealed"][token] == "jane.reveal@example.com"
    assert body["not_found"] == []


async def test_list_documents_returns_newest_first_with_total(client: AsyncClient) -> None:
    first = await upload_and_wait_ready(
        client, "list-a.md", b"# A\n\nAlpha content.", "text/markdown"
    )
    second = await upload_and_wait_ready(
        client, "list-b.md", b"# B\n\nBeta content.", "text/markdown"
    )

    resp = await client.get("/api/v1/documents", params={"limit": 200})
    assert resp.status_code == 200
    body = resp.json()
    ids = [d["id"] for d in body["documents"]]
    assert body["total"] >= 2
    assert ids.index(second["id"]) < ids.index(first["id"])
    listed = next(d for d in body["documents"] if d["id"] == second["id"])
    assert listed["filename"] == "list-b.md"
    assert listed["status"] == "ready"
    assert listed["chunk_count"] == second["chunk_count"]


async def test_list_documents_filters_by_status(client: AsyncClient) -> None:
    await upload_and_wait_ready(client, "filter.md", b"# F\n\nFilter me.", "text/markdown")
    resp = await client.get("/api/v1/documents", params={"status": "ready", "limit": 200})
    assert resp.status_code == 200
    assert resp.json()["documents"]
    assert all(d["status"] == "ready" for d in resp.json()["documents"])


async def test_delete_document_removes_chunks_vectors_and_keyword_index(
    client: AsyncClient,
) -> None:
    from app.embeddings.registry import get_embedder
    from app.stores.bm25 import get_bm25_index
    from app.stores.vector import get_vector_store

    doc = await upload_and_wait_ready(
        client,
        "delete-me.md",
        b"# Zeppelin Maintenance\n\nThe zeppelin hangar is inspected every quartz cycle.",
        "text/markdown",
    )
    document_id = doc["id"]
    await wait_for_enrichment(client, document_id)
    assert get_bm25_index().search("zeppelin hangar", k=3, doc_id=document_id)

    resp = await client.delete(f"/api/v1/documents/{document_id}")
    assert resp.status_code == 200
    assert resp.json()["chunks_removed"] == doc["chunk_count"]

    assert (await client.get(f"/api/v1/documents/{document_id}")).status_code == 404
    assert get_bm25_index().search("zeppelin hangar", k=3, doc_id=document_id) == []
    query = get_embedder().embed_one("zeppelin hangar")
    assert get_vector_store().query(query, k=3, where={"doc_id": document_id}) == []


async def test_delete_unknown_document_is_404(client: AsyncClient) -> None:
    resp = await client.delete("/api/v1/documents/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["code"] == "document_not_found"


async def test_sample_document_goes_through_real_ingestion(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/documents/sample")
    assert resp.status_code == 200
    doc = await wait_for_document(client, resp.json()["document_id"], timeout=300.0)
    assert doc["status"] == "ready"
    assert doc["filename"] == "northwind_remote_work_travel_policy.pdf"
    assert doc["chunk_count"] > 0


async def test_a_ready_document_can_be_deleted_while_its_graph_is_still_being_read(
    client: AsyncClient,
) -> None:
    """Background enrichment is optional work; it is stopped, not waited for."""
    resp = await client.post("/api/v1/documents/sample")
    document_id = resp.json()["document_id"]
    for _ in range(240):
        doc = (await client.get(f"/api/v1/documents/{document_id}")).json()
        if doc["status"] == "ready":
            break
        await asyncio.sleep(0.5)
    assert doc["status"] == "ready"

    deleted = await client.delete(f"/api/v1/documents/{document_id}")
    assert deleted.status_code == 200, deleted.text
    assert (await client.get(f"/api/v1/documents/{document_id}")).status_code == 404
