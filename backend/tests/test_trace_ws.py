from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.main import app


def test_trace_ws_connects_cleanly_with_no_history() -> None:
    with TestClient(app) as client, client.websocket_connect("/ws/trace/no-such-session"):
        pass  # connect + clean disconnect, no crash, nothing to replay


def _wait_for_ready_sync(client: TestClient, document_id: str, timeout: float = 90.0) -> None:
    """TestClient has no async client fixture to share conftest's wait_for_document with, but
    each client.get() call still pumps the same background event loop that the detached
    ingestion task runs on (see app/ingestion/service.py) — so plain polling works here too."""
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(f"/api/v1/documents/{document_id}").json()
        if body["status"] in ("ready", "failed", "cancelled"):
            assert body["status"] == "ready", body.get("error_message")
            return
        if time.monotonic() > deadline:
            raise AssertionError(f"document {document_id} never became ready: {body}")
        time.sleep(0.2)


def test_trace_ws_replays_real_ingestion_trace_history() -> None:
    with TestClient(app) as client:
        content = b"# Note\n\nThe office is closed on public holidays."
        files = {"file": ("note.md", content, "text/markdown")}
        upload = client.post("/api/v1/documents/upload", files=files)
        document_id = upload.json()["document_id"]
        _wait_for_ready_sync(client, document_id)

        # Ingestion now runs as a detached background job (see app/ingestion/service.py) — by
        # the time it's reached "ready" above, "upload" and "parse" are long since done, so
        # this connects as a late subscriber and must see those real stages replayed from
        # history, not nothing and not a synthesized/fake event.
        with client.websocket_connect(f"/ws/trace/{document_id}") as ws:
            stages = []
            for _ in range(3):
                event = ws.receive_json()
                assert event["session_id"] == document_id
                stages.append(event["stage"])
            assert "upload" in stages
            assert "parse" in stages
