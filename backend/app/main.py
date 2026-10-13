"""Veritas FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.agents.runs import reconcile_interrupted_runs
from app.api.routes.analytics import router as analytics_router
from app.api.routes.architecture import router as architecture_router
from app.api.routes.audit import router as audit_router
from app.api.routes.chat import router as chat_router
from app.api.routes.council import router as council_router
from app.api.routes.documents import router as documents_router
from app.api.routes.evaluation import router as evaluation_router
from app.api.routes.graph import router as graph_router
from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.models import router as models_router
from app.api.routes.pii import router as pii_router
from app.api.routes.profiler import router as profiler_router
from app.api.routes.rag import router as rag_router
from app.api.routes.redteam import router as redteam_router
from app.api.routes.reports import router as reports_router
from app.api.routes.retrieval import router as retrieval_router
from app.api.routes.runs import router as runs_router
from app.api.routes.trace import router as trace_router
from app.core import jobs, runtime_settings
from app.core.config import get_settings
from app.core.db import init_db
from app.core.errors import AppError, app_error_handler, unhandled_error_handler
from app.core.logging import configure_logging
from app.core.preflight import PreflightReport, run_preflight
from app.ingestion.service import reconcile_interrupted_jobs
from app.llm.models_catalog import reconcile_selection
from app.stores.bm25 import rebuild_bm25_index

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

_preflight_task: asyncio.Task[PreflightReport] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _preflight_task
    await init_db()
    await runtime_settings.load()
    dropped = await reconcile_selection()
    if dropped:
        logger.warning("Saved model choices no longer installed were reset: %s", dropped)

    reconciled = await reconcile_interrupted_jobs()
    if reconciled:
        logger.warning(
            "Marked %d document(s) 'failed' — they were queued/running when the backend last "
            "stopped and have no process left to finish them. Re-upload to retry.",
            reconciled,
        )

    reconciled_runs = await reconcile_interrupted_runs()
    if reconciled_runs:
        logger.warning(
            "Marked %d chat run(s) 'failed' — they were in progress when the backend last "
            "stopped and have no process left to finish them.",
            reconciled_runs,
        )

    orphaned = await jobs.reconcile_orphaned_jobs()
    if orphaned:
        logger.warning("Marked %d background job(s) 'failed' — interrupted by a restart.", orphaned)

    # Before anything can search: the keyword index is in-memory only (see app/stores/bm25.py).
    await rebuild_bm25_index()

    # Deliberately NOT awaited: preflight can take minutes on a cold model cache (see
    # docs/TROUBLESHOOTING.md), and the server should start accepting connections — including
    # GET /health, which reports preflight's live progress — immediately rather than appearing
    # hung for however long that takes.
    _preflight_task = asyncio.create_task(run_preflight())

    yield


app = FastAPI(title="Veritas", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


@app.middleware("http")
async def add_trace_id(request: Request, call_next):
    request.state.trace_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Trace-Id"] = request.state.trace_id
    return response


app.include_router(health_router, prefix="/api/v1")
app.include_router(architecture_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(pii_router, prefix="/api/v1")
app.include_router(retrieval_router, prefix="/api/v1")
app.include_router(graph_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(runs_router, prefix="/api/v1")
app.include_router(reports_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(redteam_router, prefix="/api/v1")
app.include_router(profiler_router, prefix="/api/v1")
app.include_router(evaluation_router, prefix="/api/v1")
app.include_router(council_router, prefix="/api/v1")
app.include_router(jobs_router, prefix="/api/v1")
app.include_router(rag_router, prefix="/api/v1")
app.include_router(models_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(trace_router)  # /ws/trace/{session_id} — no /api/v1 prefix, per docs/API.md
