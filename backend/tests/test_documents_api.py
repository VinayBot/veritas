from __future__ import annotations

from conftest import wait_for_document
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
