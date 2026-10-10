"""Orchestrates one document's ingestion as a real, persisted job — queued -> running ->
ready | failed | cancelled — instead of one giant synchronous call. The upload endpoint saves
the file and returns almost immediately; the actual pipeline runs as a detached background
task so a slow or genuinely stuck stage can never hold the HTTP request open forever. Every
stage is timeout-bounded, so a slow stage degrades to a clear, visible failure instead of an
invisible hang. The critical path (parse..index) marks the document "ready" for chat as soon
as it finishes; graph/profile/advisor run afterward as a separate, non-blocking enrichment
phase with their own status. See docs/TROUBLESHOOTING.md and docs/DECISIONS.md for the
incident this was built to fix.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.tracing import trace_bus
from app.graphrag.service import build_graph_for_document
from app.ingestion.models import Document
from app.ingestion.refiner import refine
from app.ingestion.registry import parse_file, supported_extensions
from app.ingestion.scraper import RobotsDisallowedError, ScrapeResult, SsrfBlockedError, scrape_url
from app.privacy.service import tokenize_text
from app.profiler import service as profiler_service
from app.retrieval.indexing import index_document

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


# Per-stage timeout budgets, in seconds. Generous enough to cover a cold-cache first run (a
# real, measured run of this exact pipeline — see docs/DECISIONS.md — took ~249s total, almost
# entirely the "parse" and "embed" stages downloading their models for the first time), tight
# enough that a genuinely stuck call fails clearly rather than hanging the UI forever.
STAGE_TIMEOUTS: dict[str, float] = {
    "parse": 300.0,
    "refine": 30.0,
    "pii_vault": 60.0,
    "chunk": 30.0,
    "embed": 180.0,
    "index": 60.0,
    "graph": 300.0,
    "profile": 60.0,
    "advisor": 300.0,
}

CRITICAL_PATH_STAGES = ("parse", "refine", "pii_vault", "chunk_embed_index")
ENRICHMENT_STAGES = ("graph", "profile", "advisor")

# Strong references to detached ingestion tasks — asyncio only holds a *weak* reference to a
# task created with create_task, so without this a task can be silently garbage-collected
# mid-flight. Discarded automatically once the task finishes (success or failure).
_background_tasks: set[asyncio.Task[None]] = set()


def _track(task: asyncio.Task[None]) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _uploads_dir() -> Path:
    settings = get_settings()
    path = settings.data_dir / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _create_document_row(
    document_id: str, filename: str, source_type: str, source_url: str | None, mime_type: str | None
) -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            Document(
                id=document_id,
                filename=filename,
                source_type=source_type,
                source_url=source_url,
                mime_type=mime_type,
                status="queued",
                fix_log=[],
                pii_counts={},
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


async def _update_document(document_id: str, **fields: Any) -> None:
    async with session_scope() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        for key, value in fields.items():
            setattr(doc, key, value)
        doc.updated_at = datetime.now(UTC)
        await session.commit()


class _Cancelled(Exception):
    """Raised at a stage boundary when the job was cancelled since the previous stage started —
    see cancel_ingestion()'s docstring on why this is cooperative, not pre-emptive."""


async def _mark_stage_running(document_id: str, stage: str) -> None:
    doc = await get_document(document_id)
    if doc is not None and doc.status == "cancelled":
        raise _Cancelled()
    await _update_document(document_id, status="running", current_stage=stage)


async def _mark_failed(document_id: str, stage: str, exc: BaseException) -> None:
    if isinstance(exc, TimeoutError):
        timeout = STAGE_TIMEOUTS.get(stage, 120.0)
        message = (
            f"'{stage}' did not finish within {timeout:.0f}s. If this is one of the first "
            "documents you've ingested, the backend may still be downloading a model for the "
            "first time — check the backend logs, then retry; it should be fast afterward."
        )
    else:
        message = str(exc) or exc.__class__.__name__
    logger.error(
        "Ingestion stage %r failed for document %s: %s",
        stage,
        document_id,
        message,
        exc_info=exc,
    )
    await _update_document(
        document_id,
        status="failed",
        current_stage=stage,
        error_stage=stage,
        error_message=message[:2000],
    )


async def reconcile_interrupted_jobs() -> int:
    """Run once at startup: an in-memory asyncio task doesn't survive a process restart, so
    any document still "queued"/"running" from a previous process lifetime is permanently
    stuck with nothing left to ever update it. Marks each one "failed" with a clear reason
    instead of leaving it spinning forever in the UI. Returns the count fixed, for the
    startup log."""
    async with session_scope() as session:
        from sqlalchemy import select

        rows = (
            (
                await session.execute(
                    select(Document).where(Document.status.in_(["queued", "running"]))
                )
            )
            .scalars()
            .all()
        )
        for doc in rows:
            doc.status = "failed"
            doc.error_stage = doc.current_stage
            doc.error_message = (
                "Ingestion was interrupted by a backend restart before this stage finished. "
                "Please re-upload the document."
            )
            doc.updated_at = datetime.now(UTC)
        await session.commit()
        return len(rows)


async def _timed(document_id: str, stage: str, awaitable: Any) -> Any:
    try:
        return await asyncio.wait_for(awaitable, timeout=STAGE_TIMEOUTS[stage])
    except TimeoutError as exc:
        raise TimeoutError(str(exc)) from exc


async def _run_critical_path(
    document_id: str, raw_text: str, ocr_confidence: float | None
) -> list | None:
    """Refine, PII-mask, chunk, embed, index — the minimum needed before the document can be
    chatted with. Marks the document "ready" as soon as this succeeds; never touches
    graph/profile/advisor. Owns its own failure handling (so the stage it reports as failed is
    always the one actually running, not whatever the caller's parse-stage variable last said)
    — returns None, having already recorded the failure, instead of propagating the exception.
    """
    stage = "refine"
    try:
        await _mark_stage_running(document_id, stage)
        async with trace_bus.stage(
            document_id, "refine", from_stage="parse", to_stage="pii_vault"
        ) as h:
            result = await _timed(
                document_id,
                stage,
                asyncio.to_thread(refine, raw_text, ocr_confidence=ocr_confidence),
            )
            h.set_metric("quality_before", result.quality_before)
            h.set_metric("quality_after", result.quality_after)
            h.set_metric("fix_count", len(result.fix_log))
            h.set_output(f"quality {result.quality_before}->{result.quality_after}")

        stage = "pii_vault"
        await _mark_stage_running(document_id, stage)
        async with trace_bus.stage(
            document_id, "pii_vault", from_stage="refine", to_stage="chunk"
        ) as h:
            tokenized = await _timed(
                document_id, stage, tokenize_text(result.text, document_id=document_id)
            )
            h.set_metric("pii_counts", tokenized.pii_counts)
            h.set_output(f"{sum(tokenized.pii_counts.values())} PII spans tokenized")

        stage = "chunk_embed_index"
        await _mark_stage_running(document_id, "chunk")
        # chunk/embed/index share one timeout budget (index_document does all three as one
        # real pipeline so chunks never drift out of sync between the dense/sparse stores —
        # see app/retrieval/indexing.py); embed's model-download cost dominates on a cold cache.
        chunks = await asyncio.wait_for(
            index_document(document_id, tokenized.masked_text),
            timeout=STAGE_TIMEOUTS["embed"] + STAGE_TIMEOUTS["chunk"] + STAGE_TIMEOUTS["index"],
        )
    except _Cancelled:
        return None
    except Exception as exc:  # noqa: BLE001 — the whole point: never let a stage hang silently
        await _mark_failed(document_id, stage, exc)
        return None

    await _update_document(
        document_id,
        status="ready",
        current_stage=None,
        raw_text_chars=len(raw_text),
        quality_score_before=result.quality_before,
        quality_score_after=result.quality_after,
        fix_log=result.fix_log,
        language=result.language,
        ocr_confidence=ocr_confidence,
        pii_counts=tokenized.pii_counts,
        masked_text=tokenized.masked_text,
        chunk_count=len(chunks),
        chunk_strategy=chunks[0].strategy if chunks else None,
    )
    return chunks


async def _run_enrichment(
    document_id: str,
    masked_text: str,
    language: str | None,
    ocr_confidence: float | None,
    chunks: list,
) -> None:
    """Graph extraction, profiling, and the advisor tournament — real, but slow and LLM-heavy,
    and never load-bearing for whether the document can be chatted with. Runs after the
    critical path, with its own status field, so a slow/failed enrichment phase never leaves
    the document stuck un-chattable."""
    await _update_document(document_id, enrichment_status="running")
    try:
        stage = "graph"
        async with trace_bus.stage(
            document_id, "graph", from_stage="index", to_stage="profile"
        ) as h:
            graph_stats = await _timed(
                document_id, stage, build_graph_for_document(document_id, chunks)
            )
            for key, value in graph_stats.items():
                h.set_metric(key, value)
            h.set_output(f"{graph_stats['entities']} entities, {graph_stats['triples']} triples")
        await _update_document(
            document_id,
            graph_entity_count=graph_stats["entities"],
            graph_triple_count=graph_stats["triples"],
        )

        stage = "profile"
        async with trace_bus.stage(
            document_id, "profile", from_stage="graph", to_stage="advisor"
        ) as h:
            doc_profile = await _timed(
                document_id,
                stage,
                profiler_service.profile(document_id, masked_text, language, ocr_confidence),
            )
            h.set_metric("document_type", doc_profile.document_type)
            h.set_metric("tokens", doc_profile.tokens)
            h.set_metric("relation_density", doc_profile.relation_density)
            h.set_output(f"{doc_profile.document_type}, {doc_profile.tokens} tokens")

        stage = "advisor"
        async with trace_bus.stage(document_id, "advisor", from_stage="profile") as h:
            recommendation = await _timed(
                document_id,
                stage,
                profiler_service.run_advisor(document_id, masked_text, doc_profile),
            )
            if recommendation is None:
                h.set_output("skipped — not enough chunks yet for a meaningful comparison")
            else:
                h.set_metric("suggested_mode", recommendation.suggested_mode)
                h.set_metric("gain_ndcg_points", recommendation.gain_ndcg_points)
                h.set_output(
                    f"suggested {recommendation.suggested.config.name} "
                    f"({recommendation.gain_ndcg_points:+.1f} nDCG@5 pts over baseline)"
                )

        await _update_document(document_id, enrichment_status="done")
    except _Cancelled:
        await _update_document(document_id, enrichment_status="cancelled")
    except Exception as exc:  # noqa: BLE001 — enrichment must never crash the process either
        logger.error(
            "Enrichment stage %r failed for document %s: %s",
            stage,
            document_id,
            exc,
            exc_info=exc,
        )
        await _update_document(
            document_id, enrichment_status="failed", enrichment_error=str(exc)[:2000]
        )


async def _run_pipeline(
    document_id: str, dest_path: Path, raw_text_source: str, is_url: bool
) -> None:
    """The full background job: parse -> critical path -> ready -> enrichment. Any exception
    anywhere in the critical path marks the document "failed" with the exact stage and
    message — nothing is ever left silently stuck as "running"."""
    stage = "parse"
    try:
        await _mark_stage_running(document_id, stage)
        async with trace_bus.stage(
            document_id, "parse", from_stage="upload", to_stage="refine"
        ) as h:
            if is_url:
                parsed_text, ocr_confidence = raw_text_source, None
                h.set_metric("chars", len(parsed_text))
            else:
                # Unsupported extensions are rejected synchronously in ingest_upload() before
                # a job is ever queued, so parse_file() here can only fail on a file that *is*
                # a supported extension but unreadable (empty/corrupt/password-protected,
                # surfaced as ParseError — see docling_parser.py) — handled uniformly by the
                # outer except below, same as any other stage failure.
                parsed = await _timed(document_id, stage, asyncio.to_thread(parse_file, dest_path))
                parsed_text, ocr_confidence = parsed.text, parsed.ocr_confidence
                h.set_metric("chars", len(parsed_text))
                h.set_metric("pages", parsed.pages)

        chunks = await _run_critical_path(document_id, parsed_text, ocr_confidence)
    except _Cancelled:
        return
    except Exception as exc:  # noqa: BLE001 — the whole point: never let a stage hang silently
        await _mark_failed(document_id, stage, exc)
        return

    if chunks is None:
        return  # _run_critical_path already recorded its own failure/cancellation

    doc = await get_document(document_id)
    masked_text = doc.masked_text if doc else None
    language = doc.language if doc else None
    if masked_text is not None:
        task = asyncio.ensure_future(
            _run_enrichment(document_id, masked_text, language, ocr_confidence, chunks)
        )
        _track(task)


async def ingest_upload(filename: str, content: bytes, mime_type: str | None) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in supported_extensions():
        raise IngestionError(
            "unsupported_format",
            f"'{extension or filename}' is not a supported file type. "
            f"Supported extensions: {', '.join(supported_extensions())}",
        )

    document_id = str(uuid.uuid4())
    await _create_document_row(document_id, filename, "upload", None, mime_type)

    dest_dir = _uploads_dir() / document_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"original{extension}"

    async with trace_bus.stage(document_id, "upload", to_stage="parse") as h:
        dest_path.write_bytes(content)
        h.set_metric("bytes", len(content))

    task = asyncio.ensure_future(_run_pipeline(document_id, dest_path, "", is_url=False))
    _track(task)
    return document_id


async def ingest_url(url: str, crawl_depth: int = 0) -> str:
    document_id = str(uuid.uuid4())
    await _create_document_row(document_id, url, "url", url, "text/html")

    async with trace_bus.stage(document_id, "upload", to_stage="parse", input_preview=url) as h:
        h.set_metric("source", "url")

    async def _scrape_then_run() -> None:
        stage = "parse"
        try:
            async with trace_bus.stage(
                document_id, "parse", from_stage="upload", to_stage="refine"
            ) as h:
                try:
                    result: ScrapeResult = await _timed(
                        document_id, stage, asyncio.to_thread(scrape_url, url, crawl_depth)
                    )
                except (SsrfBlockedError, RobotsDisallowedError) as exc:
                    raise IngestionError("scrape_blocked", str(exc)) from exc

                if not result.pages:
                    raise IngestionError(
                        "scrape_empty", f"Could not extract any content from {url}"
                    )

                combined = "\n\n---\n\n".join(
                    f"<!-- source: {p.url} -->\n{p.text}" for p in result.pages if p.text
                )
                h.set_metric("pages_scraped", len(result.pages))
                h.set_metric("chars", len(combined))

            chunks = await _run_critical_path(document_id, combined, None)
        except _Cancelled:
            return
        except Exception as exc:  # noqa: BLE001
            await _mark_failed(document_id, stage, exc)
            return

        if chunks is None:
            return  # _run_critical_path already recorded its own failure/cancellation

        doc = await get_document(document_id)
        if doc and doc.masked_text is not None:
            enrich_task = asyncio.ensure_future(
                _run_enrichment(document_id, doc.masked_text, doc.language, None, chunks)
            )
            _track(enrich_task)

    task = asyncio.ensure_future(_scrape_then_run())
    _track(task)
    return document_id


async def retry_ingestion(document_id: str) -> None:
    """Re-runs ingestion for a document that previously failed, from the beginning — simpler
    and more honest than trying to resume mid-pipeline from partially-written state, at the
    (acceptable) cost of re-doing a little work that may have already succeeded."""
    doc = await get_document(document_id)
    if doc is None:
        raise IngestionError("document_not_found", f"No document with id {document_id}")
    if doc.status not in ("failed", "cancelled"):
        raise IngestionError(
            "retry_not_allowed",
            f"Document is '{doc.status}', not failed/cancelled — nothing to retry",
        )

    await _update_document(
        document_id, status="queued", current_stage=None, error_message=None, error_stage=None
    )

    if doc.source_type == "url" and doc.source_url:
        task = asyncio.ensure_future(_retry_url(document_id, doc.source_url))
    else:
        extension = Path(doc.filename).suffix.lower()
        dest_path = _uploads_dir() / document_id / f"original{extension}"
        if not dest_path.exists():
            await _update_document(
                document_id,
                status="failed",
                error_message="Original uploaded file is no longer available — please re-upload.",
            )
            return
        task = asyncio.ensure_future(_run_pipeline(document_id, dest_path, "", is_url=False))
    _track(task)


async def _retry_url(document_id: str, url: str) -> None:
    stage = "parse"
    try:
        async with trace_bus.stage(
            document_id, "parse", from_stage="upload", to_stage="refine"
        ) as h:
            try:
                result: ScrapeResult = await _timed(
                    document_id, stage, asyncio.to_thread(scrape_url, url, 0)
                )
            except (SsrfBlockedError, RobotsDisallowedError) as exc:
                raise IngestionError("scrape_blocked", str(exc)) from exc
            if not result.pages:
                raise IngestionError("scrape_empty", f"Could not extract any content from {url}")
            combined = "\n\n---\n\n".join(
                f"<!-- source: {p.url} -->\n{p.text}" for p in result.pages if p.text
            )
            h.set_metric("pages_scraped", len(result.pages))
            h.set_metric("chars", len(combined))
        chunks = await _run_critical_path(document_id, combined, None)
    except _Cancelled:
        return
    except Exception as exc:  # noqa: BLE001
        await _mark_failed(document_id, stage, exc)
        return

    if chunks is None:
        return  # _run_critical_path already recorded its own failure/cancellation

    doc = await get_document(document_id)
    if doc and doc.masked_text is not None:
        enrich_task = asyncio.ensure_future(
            _run_enrichment(document_id, doc.masked_text, doc.language, None, chunks)
        )
        _track(enrich_task)


async def cancel_ingestion(document_id: str) -> None:
    """Best-effort, cooperative cancellation: there's no way to safely pre-empt a stage already
    mid-flight inside a model's synchronous call, so this just records the request. A stage
    boundary checks for it before starting the next stage and stops there rather than
    pretending to abort instantly."""
    doc = await get_document(document_id)
    if doc is None:
        raise IngestionError("document_not_found", f"No document with id {document_id}")
    if doc.status not in ("queued", "running"):
        raise IngestionError("cancel_not_allowed", f"Document is '{doc.status}', not in progress")
    await _update_document(document_id, status="cancelled")


async def get_document(document_id: str) -> Document | None:
    async with session_scope() as session:
        return await session.get(Document, document_id)
