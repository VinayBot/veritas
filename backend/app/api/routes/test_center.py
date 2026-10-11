"""Test Center: an in-app self-test and sample-document loader so a user can verify the whole
stack is healthy without reading backend logs. Reuses the real preflight check functions
(app/core/preflight.py) rather than re-implementing them — this is the same embedder/ollama/
vector_store check startup already runs, just re-run on demand — plus two checks preflight
doesn't cover that specifically matter for "is this instance usable right now": can it reach
its own metadata database, and can it actually schedule and run a background task (the same
mechanism every ingestion job depends on).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import text

from app.api.schemas.documents import UploadResponse
from app.api.schemas.test_center import SelfTestCheck, SelfTestResponse
from app.core.db import session_scope
from app.core.errors import AppError
from app.core.preflight import (
    check_ollama,
    check_vector_store_write,
    timed_check,
    warm_embedder,
)
from app.ingestion import service

router = APIRouter(tags=["test-center"])

# backend/app/api/routes/test_center.py -> backend/app/api/routes -> backend/app/api ->
# backend/app -> backend -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_SAMPLE_PDF = _REPO_ROOT / "data" / "demo" / "northwind_remote_work_travel_policy.pdf"


async def _check_database() -> str:
    async with session_scope() as session:
        await session.execute(text("SELECT 1"))
    return "query ok"


async def _check_worker() -> str:
    """Proves the event loop can actually schedule and complete a background task promptly —
    the same asyncio.ensure_future mechanism every ingestion job's critical path and
    enrichment phase depends on (app/ingestion/service.py)."""
    event = asyncio.Event()

    async def _set_soon() -> None:
        await asyncio.sleep(0.01)
        event.set()

    task = asyncio.ensure_future(_set_soon())
    try:
        await asyncio.wait_for(event.wait(), timeout=2.0)
    finally:
        if not task.done():
            task.cancel()
    return "background task scheduling ok"


@router.get("/test-center/self-test", response_model=SelfTestResponse)
async def self_test() -> SelfTestResponse:
    results = await asyncio.gather(
        timed_check("database", _check_database),
        timed_check("worker", _check_worker),
        timed_check("embedder", warm_embedder),
        timed_check("ollama", check_ollama),
        timed_check("vector_store", check_vector_store_write),
    )
    checks = [
        SelfTestCheck(name=r.name, ok=r.ok, detail=r.detail, duration_ms=round(r.duration_ms, 1))
        for r in results
    ]
    return SelfTestResponse(checks=checks, all_ok=all(c.ok for c in checks))


@router.post("/test-center/load-sample", response_model=UploadResponse)
async def load_sample() -> UploadResponse:
    """Uploads the project's own real demo document through the exact same ingest_upload()
    path a real file upload takes — not a parallel/mocked flow."""
    if not _SAMPLE_PDF.exists():
        raise AppError("sample_not_found", f"Built-in sample not found at {_SAMPLE_PDF}", 500)
    content = _SAMPLE_PDF.read_bytes()
    document_id = await service.ingest_upload(_SAMPLE_PDF.name, content, "application/pdf")
    return UploadResponse(document_id=document_id, job_id=document_id)
