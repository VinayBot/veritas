from __future__ import annotations

import json

from conftest import wait_for_document, wait_for_enrichment
from httpx import AsyncClient


def _parse_sse(text: str) -> list[tuple[str, str]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_line, data_line = block.split("\n", 1)
        event = event_line.removeprefix("event: ")
        data = data_line.removeprefix("data: ")
        events.append((event, data))
    return events


async def _upload_policy_doc(client: AsyncClient) -> str:
    files = {
        "file": (
            "policy.md",
            b"# Vacation Policy\n\nEmployees accrue two paid vacation days per month of "
            b"service, up to a maximum of twenty-four days per year.",
            "text/markdown",
        )
    }
    resp = await client.post("/api/v1/documents/upload", files=files)
    document_id = resp.json()["document_id"]
    await wait_for_document(client, document_id)
    return document_id


async def test_chat_hybrid_mode_end_to_end(client: AsyncClient) -> None:
    document_id = await _upload_policy_doc(client)
    resp = await client.post(
        "/api/v1/chat",
        json={
            "message": "How much vacation do employees get?",
            "document_id": document_id,
            "mode": "hybrid",
        },
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    event_types = [e for e, _ in events]
    assert "session" in event_types
    assert "token" in event_types
    assert "done" in event_types

    done_data = json.loads(next(d for e, d in events if e == "done"))
    assert done_data["report_id"]

    report_resp = await client.get(f"/api/v1/reports/{done_data['report_id']}")
    assert report_resp.status_code == 200
    report = report_resp.json()
    assert report["mode"] == "hybrid"
    assert report["answer"]


async def test_chat_graph_mode_end_to_end(client: AsyncClient) -> None:
    files = {
        "file": (
            "about.md",
            b"Emberwood Studios collaborated with Hollowpine Games on a new title.",
            "text/markdown",
        )
    }
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]
    await wait_for_enrichment(client, document_id)

    resp = await client.post(
        "/api/v1/chat",
        json={"message": "Emberwood Studios", "document_id": document_id, "mode": "graph"},
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    assert any(e == "done" for e, _ in events)


async def test_chat_agentic_mode_end_to_end(client: AsyncClient) -> None:
    document_id = await _upload_policy_doc(client)
    resp = await client.post(
        "/api/v1/chat",
        json={
            "message": "How much vacation do employees accrue per month?",
            "document_id": document_id,
            "mode": "agentic",
        },
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    event_types = [e for e, _ in events]
    assert "done" in event_types

    agent_steps_data = json.loads(next(d for e, d in events if e == "agent_steps"))
    nodes = {s["node"] for s in agent_steps_data}
    assert "synthesizer" in nodes


async def test_chat_invalid_mode_returns_error_event(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/chat", json={"message": "hello", "mode": "nonsense"})
    assert (
        resp.status_code == 200
    )  # SSE streams always 200; the error is an event, not a status code
    events = _parse_sse(resp.text)
    assert events[0][0] == "error"


async def test_chat_second_identical_question_hits_semantic_cache(client: AsyncClient) -> None:
    document_id = await _upload_policy_doc(client)
    body = {
        "message": "How much vacation do employees get per month?",
        "document_id": document_id,
        "mode": "hybrid",
    }
    first = await client.post("/api/v1/chat", json=body)
    first_events = _parse_sse(first.text)
    first_session = json.loads(next(d for e, d in first_events if e == "session"))
    assert first_session["cache_hit"] is False

    second = await client.post("/api/v1/chat", json=body)
    second_events = _parse_sse(second.text)
    second_session = json.loads(next(d for e, d in second_events if e == "session"))
    assert second_session["cache_hit"] is True


async def test_report_not_found_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/reports/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["code"] == "report_not_found"


async def test_chat_response_carries_a_real_estimated_quality_report(client: AsyncClient) -> None:
    document_id = await _upload_policy_doc(client)
    resp = await client.post(
        "/api/v1/chat",
        json={
            "message": "How much vacation do employees get?",
            "document_id": document_id,
            "mode": "hybrid",
        },
    )
    events = _parse_sse(resp.text)
    quality = json.loads(next(d for e, d in events if e == "quality"))
    assert quality["label"] == "estimated"
    assert 0.0 <= quality["relevancy"] <= 1.0
    assert 0.0 <= quality["citation_validity"] <= 1.0
    assert 0.0 <= quality["confidence"] <= 1.0
    if quality["faithfulness"] is not None:
        assert 0.0 <= quality["faithfulness"] <= 1.0

    done_data = json.loads(next(d for e, d in events if e == "done"))
    report = await client.get(f"/api/v1/reports/{done_data['report_id']}")
    assert report.json()["quality"] == quality
