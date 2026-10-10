from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATA_DIR", "./var/test-data")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./var/test-data/test.db")
os.environ.setdefault("PII_HMAC_SECRET", "test-secret")
os.environ.setdefault("PII_VAULT_KEY", "2OMpEZVoa7egSJnHWsOhcj5Ir-PV_EJXOfVA047Z29g=")

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import init_db
from app.main import app

TERMINAL_STATUSES = ("ready", "failed", "cancelled")


async def wait_for_document(
    client: AsyncClient, document_id: str, *, timeout: float = 90.0
) -> dict:
    """Ingestion now runs as a detached background job (see app/ingestion/service.py and
    docs/TROUBLESHOOTING.md) — `POST /documents/upload` returns as soon as the job is queued,
    not once it's ready. Every test that needs a usable document polls GET /documents/{id}
    until it reaches a terminal status, exactly as the real frontend does."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        resp = await client.get(f"/api/v1/documents/{document_id}")
        body = resp.json()
        if body.get("status") in TERMINAL_STATUSES:
            return body
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(
                f"document {document_id} did not reach a terminal status within "
                f"{timeout}s (last status: {body.get('status')!r}, stage: "
                f"{body.get('current_stage')!r})"
            )
        await asyncio.sleep(0.2)


ENRICHMENT_TERMINAL_STATUSES = ("done", "failed", "cancelled")


async def wait_for_enrichment(
    client: AsyncClient, document_id: str, *, timeout: float = 90.0
) -> dict:
    """Graph extraction, profiling, and the advisor tournament run as a separate background
    phase *after* the document is already "ready" for chat (see _run_enrichment in
    app/ingestion/service.py) — tests of /graph or anything reading graph_entity_count must
    wait for enrichment_status to land on a terminal value too, not just status=="ready"."""
    doc = await wait_for_document(client, document_id, timeout=timeout)
    assert doc["status"] == "ready", (
        f"document {document_id} never became ready (status={doc['status']!r}), so "
        "enrichment never started"
    )
    deadline = asyncio.get_event_loop().time() + timeout
    while doc.get("enrichment_status") not in ENRICHMENT_TERMINAL_STATUSES:
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(
                f"document {document_id} enrichment did not finish within {timeout}s "
                f"(last enrichment_status: {doc.get('enrichment_status')!r})"
            )
        await asyncio.sleep(0.2)
        resp = await client.get(f"/api/v1/documents/{document_id}")
        doc = resp.json()
    return doc


async def upload_and_wait_ready(
    client: AsyncClient, filename: str, content: bytes, mime_type: str, *, timeout: float = 90.0
) -> dict:
    """Uploads a file and polls until the document is ready, failing the test immediately and
    clearly if ingestion instead failed — the shared replacement for every test's old
    "upload, assume it's instantly ready" pattern."""
    files = {"file": (filename, content, mime_type)}
    upload = await client.post("/api/v1/documents/upload", files=files)
    assert upload.status_code == 200, upload.text
    document_id = upload.json()["document_id"]
    doc = await wait_for_document(client, document_id, timeout=timeout)
    assert doc["status"] == "ready", (
        f"expected document {document_id} to become ready, got {doc['status']!r} "
        f"(stage={doc.get('error_stage')!r}, error={doc.get('error_message')!r})"
    )
    return doc


@pytest.fixture(scope="session", autouse=True)
def _fresh_test_data_dir() -> None:
    shutil.rmtree("./var/test-data", ignore_errors=True)
    Path("./var/test-data").mkdir(parents=True, exist_ok=True)


@pytest.fixture(autouse=True)
async def _db_schema() -> None:
    # autouse, and independent of the `client` fixture: plenty of tests (guardrails, the red-
    # team runner, etc.) hit the DB directly without going through the HTTP client, and need
    # the schema to exist regardless. init_db() is idempotent (create_all), so this is cheap.
    await init_db()


@pytest.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
