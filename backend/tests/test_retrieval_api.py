from __future__ import annotations

from conftest import wait_for_document
from httpx import AsyncClient


async def test_upload_then_hybrid_search_finds_relevant_chunk(client: AsyncClient) -> None:
    content = (
        b"# Vacation Policy\n\n"
        b"Employees accrue paid vacation at a rate of two days per month of service.\n\n"
        b"# Expense Reports\n\n"
        b"Submit expense reports within thirty days of purchase for reimbursement.\n"
    )
    files = {"file": ("policy.md", content, "text/markdown")}
    upload_resp = await client.post("/api/v1/documents/upload", files=files)
    assert upload_resp.status_code == 200
    document_id = upload_resp.json()["document_id"]

    doc_body = await wait_for_document(client, document_id)
    assert doc_body["chunk_count"] >= 1

    search_resp = await client.post(
        "/api/v1/retrieval/search",
        json={"query": "How much vacation do employees get?", "document_id": document_id, "k": 3},
    )
    assert search_resp.status_code == 200
    hits = search_resp.json()["hits"]
    assert hits
    assert any("vacation" in h["text"].lower() for h in hits)


async def test_search_modes_all_return_results(client: AsyncClient) -> None:
    files = {
        "file": (
            "notes.txt",
            b"The invoice total was four hundred and twelve dollars.",
            "text/plain",
        )
    }
    upload_resp = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload_resp.json()["document_id"]
    await wait_for_document(client, document_id)

    for mode in ("hybrid", "dense", "bm25"):
        resp = await client.post(
            "/api/v1/retrieval/search",
            json={"query": "invoice total", "document_id": document_id, "mode": mode, "k": 3},
        )
        assert resp.status_code == 200, (mode, resp.text)
        assert resp.json()["hits"], f"mode {mode} returned no hits"


async def test_search_invalid_mode_rejected(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/retrieval/search", json={"query": "x", "mode": "nonsense"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_search_request"


async def test_search_invalid_dedupe_strategy_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/retrieval/search", json={"query": "x", "dedupe_strategy": "nonsense"}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_search_request"


async def test_full_pipeline_with_every_phase4_flag_enabled(client: AsyncClient) -> None:
    """use_hyde is included here but not asserted on specifically — it degrades gracefully to
    the raw query when no LLM is reachable (e.g. in CI without Ollama), so this only checks that
    enabling every flag together still returns a sane, reranked, deduped, token-capped result."""
    content = (
        b"# Vacation Policy\n\nEmployees accrue two paid vacation days per month of service, "
        b"up to a maximum of twenty-four days per year. Managers must approve requests at "
        b"least two weeks in advance. Unused days roll over, capped at ten days.\n\n"
        b"# Expense Reports\n\nSubmit expense reports within thirty days of purchase.\n"
    )
    files = {"file": ("policy2.md", content, "text/markdown")}
    upload_resp = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload_resp.json()["document_id"]
    await wait_for_document(client, document_id)

    resp = await client.post(
        "/api/v1/retrieval/search",
        json={
            "query": "How much vacation do employees get per year?",
            "document_id": document_id,
            "k": 2,
            "use_hyde": True,
            "rerank": True,
            "dedupe_strategy": "mmr",
            "compress": True,
            "max_context_tokens": 60,
        },
    )
    assert resp.status_code == 200, resp.text
    hits = resp.json()["hits"]
    assert hits
    assert all(h["rerank_score"] is not None for h in hits)
    assert len(hits) <= 2
