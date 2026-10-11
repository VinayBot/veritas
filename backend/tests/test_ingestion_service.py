"""Unit + failure-injection coverage for the ingestion job state machine
(app/ingestion/service.py) — the fix for the "hangs on Ingesting..." incident (see
docs/TROUBLESHOOTING.md). Each test proves one specific resilience property: a stage
exception, a stage timeout, or an unreadable file always ends in status="failed" with a real
message, never a silent stall.
"""

from __future__ import annotations

import asyncio
import io
import threading

import pytest
from conftest import wait_for_document, wait_for_enrichment
from httpx import AsyncClient
from pypdf import PdfWriter

from app.ingestion import service


def _password_protected_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password="secret123", owner_password="secret123-owner")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


async def test_exception_in_refine_stage_marks_document_failed_with_message(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic refine failure")

    monkeypatch.setattr(service, "refine", _boom)

    files = {"file": ("notes.txt", b"Some ordinary document content.", "text/plain")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    doc = await wait_for_document(client, document_id)
    assert doc["status"] == "failed"
    assert doc["error_stage"] == "refine"
    assert "synthetic refine failure" in doc["error_message"]


async def test_exception_in_pii_vault_stage_marks_document_failed_with_message(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic pii_vault failure")

    monkeypatch.setattr(service, "tokenize_text", _boom)

    files = {"file": ("notes.txt", b"Some ordinary document content.", "text/plain")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    doc = await wait_for_document(client, document_id)
    assert doc["status"] == "failed"
    assert doc["error_stage"] == "pii_vault"
    assert "synthetic pii_vault failure" in doc["error_message"]


async def test_exception_in_index_stage_marks_document_failed_with_message(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic index failure")

    monkeypatch.setattr(service, "index_document", _boom)

    files = {"file": ("notes.txt", b"Some ordinary document content.", "text/plain")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    doc = await wait_for_document(client, document_id)
    assert doc["status"] == "failed"
    assert doc["error_stage"] == "chunk_embed_index"
    assert "synthetic index failure" in doc["error_message"]


async def test_stage_timeout_fails_clearly_instead_of_hanging_forever(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _hangs_forever(*_args: object, **_kwargs: object) -> None:
        await asyncio.sleep(999)

    monkeypatch.setattr(service, "tokenize_text", _hangs_forever)
    monkeypatch.setitem(service.STAGE_TIMEOUTS, "pii_vault", 0.2)

    files = {"file": ("notes.txt", b"Some ordinary document content.", "text/plain")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    doc = await wait_for_document(client, document_id, timeout=15.0)
    assert doc["status"] == "failed"
    assert doc["error_stage"] == "pii_vault"
    assert "did not finish within" in doc["error_message"]


async def test_enrichment_failure_never_blocks_document_readiness(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Graph extraction, profiling, and the advisor are LLM-heavy and can fail independently
    (e.g. Ollama unreachable — verified separately against a real unreachable OLLAMA_BASE_URL,
    see docs/TROUBLESHOOTING.md) — this must never prevent the document from being ready for
    chat, since chat only depends on the critical path, never on enrichment."""

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise ConnectionError("synthetic: Ollama unreachable")

    monkeypatch.setattr(service, "build_graph_for_document", _boom)

    files = {"file": ("about.md", b"Nightsong Robotics is a company.", "text/markdown")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    doc = await wait_for_enrichment(client, document_id)
    assert doc["status"] == "ready"
    assert doc["enrichment_status"] == "failed"
    assert "Ollama unreachable" in doc["enrichment_error"]


async def test_upload_zero_byte_pdf_fails_clearly_not_hangs(client: AsyncClient) -> None:
    files = {"file": ("empty.pdf", b"", "application/pdf")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    doc = await wait_for_document(client, document_id, timeout=30.0)
    assert doc["status"] == "failed"
    assert doc["error_stage"] == "parse"
    assert doc["error_message"]
    # The regression this guards: Docling's raw exception leaks an internal content-hash key
    # (e.g. "docling-parse could not load document e3b0c4...") instead of a clear message.
    assert "could not load document" not in doc["error_message"]


async def test_upload_corrupt_pdf_fails_clearly_not_hangs(client: AsyncClient) -> None:
    files = {"file": ("corrupt.pdf", b"this is not a real pdf file" * 20, "application/pdf")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    doc = await wait_for_document(client, document_id, timeout=30.0)
    assert doc["status"] == "failed"
    assert doc["error_stage"] == "parse"
    assert doc["error_message"]
    assert "could not load document" not in doc["error_message"]


async def test_upload_empty_text_file_fails_clearly_instead_of_a_silent_unusable_ready(
    client: AsyncClient,
) -> None:
    """Reproduced live: a 0-byte .txt uploaded through the real API previously ended up
    status="ready", chunk_count=0 — no error anywhere, despite the document being unable to
    answer any question. Docling's own empty-PDF case already fails clearly (ParseError from
    docling_parser.py); a plain text/markdown/csv parser has nothing to fail on and just
    returns "", which has to be caught explicitly. See docs/TROUBLESHOOTING.md."""
    files = {"file": ("empty.txt", b"", "text/plain")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    doc = await wait_for_document(client, document_id, timeout=30.0)
    assert doc["status"] == "failed"
    assert doc["error_stage"] == "parse"
    assert doc["error_message"]
    assert doc["chunk_count"] is None


async def test_upload_password_protected_pdf_fails_clearly_not_hangs(client: AsyncClient) -> None:
    files = {"file": ("protected.pdf", _password_protected_pdf_bytes(), "application/pdf")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    doc = await wait_for_document(client, document_id, timeout=30.0)
    assert doc["status"] == "failed"
    assert doc["error_stage"] == "parse"
    assert doc["error_message"]
    assert "could not load document" not in doc["error_message"]


async def test_cancel_during_queued_marks_cancelled_not_failed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reproduced as a genuine, intermittent flake (not a one-off), and a fixed sleep delay
    (tried first) wasn't reliable either — a .txt file's entire critical path (refine ->
    pii_vault -> chunk_embed_index) is fast enough with warm models, and the margin by which
    the real race was won or lost varied enough under load that no fixed duration was safe.
    Cancellation is only checked at a stage *boundary* (_mark_stage_running), and the final
    "mark ready" write at the end of _run_critical_path has no such check, so a cancellation
    that arrives after the last boundary but before that final write is silently too late.
    A real threading.Event removes the timing dependency entirely instead of hoping a sleep
    duration is long enough: refine blocks until the test has confirmed (via the cancel
    request's own 200 response, which only arrives once cancel_ingestion()'s write has
    actually completed) that the cancellation has already landed, before letting the
    pipeline continue into the next stage boundary that needs to observe it."""
    cancel_landed = threading.Event()
    real_refine = service.refine

    def _blocked_refine(*args: object, **kwargs: object):
        if not cancel_landed.wait(timeout=10):
            raise TimeoutError("test's cancel request never landed")
        return real_refine(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service, "refine", _blocked_refine)

    files = {"file": ("notes.txt", b"Some ordinary document content.", "text/plain")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    cancel_resp = await client.post(f"/api/v1/documents/{document_id}/cancel")
    assert cancel_resp.status_code == 200
    cancel_landed.set()  # cancel_ingestion()'s write is now durably committed — safe to proceed

    # Cancellation is cooperative (checked at the next stage boundary, see
    # cancel_ingestion()'s docstring) — give the in-flight task a moment to observe it.
    doc = await wait_for_document(client, document_id, timeout=15.0)
    assert doc["status"] == "cancelled"


async def test_retry_after_failure_can_succeed(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}
    real_refine = service.refine

    def _fail_once(*args: object, **kwargs: object):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic one-shot failure")
        return real_refine(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service, "refine", _fail_once)

    files = {"file": ("notes.txt", b"Some ordinary document content.", "text/plain")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]

    failed_doc = await wait_for_document(client, document_id)
    assert failed_doc["status"] == "failed"

    retry_resp = await client.post(f"/api/v1/documents/{document_id}/retry")
    assert retry_resp.status_code == 200

    doc = await wait_for_document(client, document_id)
    assert doc["status"] == "ready"
    assert calls["n"] == 2
