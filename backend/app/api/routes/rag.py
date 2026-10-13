"""RAG strategies: the registry with live availability, the workspace default, building what
a strategy needs, per-document recommendation, and measured comparison."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.chunking.base import Chunk
from app.chunking.models import ChunkRow
from app.core import jobs
from app.core.db import session_scope
from app.core.errors import AppError
from app.graphrag.service import build_graph_for_document
from app.ingestion import service as ingestion_service
from app.ingestion.models import Document
from app.profiler import service as profiler_service
from app.rag_engines import advisor, availability, compare
from app.rag_engines.registry import (
    UnknownStrategyError,
    default_strategy_id,
    get_strategy,
    list_strategies,
    set_default_strategy,
)
from app.rag_engines.variants import VariantError, build_variant
from app.stores.graph.networkx_store import get_graph_store

router = APIRouter(tags=["rag"])


class StrategyOut(BaseModel):
    id: str
    display_name: str
    description: str
    best_for: str
    components: list[str]
    kind: str
    typical_latency_ms: int
    """Median answer latency measured on this machine, once there are enough real turns."""
    measured_latency_ms: float | None
    measured_runs: int
    relative_cost: str
    min_hardware_tier: str
    suited_for: list[str]
    llm_calls: int
    available: bool
    unavailable_reason: str | None
    """"build_index" | "build_graph" when the app can fix what is missing; None otherwise."""
    action: str | None
    warning: str | None
    is_default: bool


class StrategiesResponse(BaseModel):
    default: str
    document_id: str | None
    strategies: list[StrategyOut]


class DefaultRequest(BaseModel):
    strategy: str


class PrepareRequest(BaseModel):
    document_id: str
    """Graph strategies only: build the graph again even though one exists."""
    rebuild: bool = False


class StartedJob(BaseModel):
    job_id: str


class CompareRequest(BaseModel):
    document_id: str
    strategies: list[str] = Field(min_length=1, max_length=8)
    """Exactly one of `dataset_id` (an eval set) and `query` (one question)."""
    dataset_id: str | None = None
    query: str | None = None
    """What the others are measured against. Omitted = the workspace default."""
    baseline: str | None = None


class ComparisonOut(BaseModel):
    id: str
    document_id: str
    created_at: datetime
    result: dict[str, Any]


class ComparisonListOut(BaseModel):
    comparisons: list[ComparisonOut]


def _unknown(exc: UnknownStrategyError) -> AppError:
    return AppError("invalid_strategy", str(exc), 422)


async def _document(document_id: str) -> Document:
    doc = await ingestion_service.get_document(document_id)
    if doc is None:
        raise AppError("document_not_found", f"No document with id {document_id}", 404)
    return doc


@router.get("/rag/strategies", response_model=StrategiesResponse)
async def strategies(document_id: str | None = None) -> StrategiesResponse:
    """Every registered strategy with whether it can run right now (for `document_id` when
    given) and, if not, the reason and what would fix it."""
    document = await _document(document_id) if document_id else None
    llm = await availability.llm_state()
    default = default_strategy_id()
    out = []
    for spec in list_strategies():
        state = await availability.check(spec, document, llm)
        measured, runs = await compare.measured_latency_ms(spec.id)
        out.append(
            StrategyOut(
                id=spec.id,
                display_name=spec.display_name,
                description=spec.description,
                best_for=spec.best_for,
                components=list(spec.components),
                kind=spec.kind,
                typical_latency_ms=spec.typical_latency_ms,
                measured_latency_ms=measured if runs >= compare.MIN_MEASURED_RUNS else None,
                measured_runs=runs,
                relative_cost=spec.relative_cost,
                min_hardware_tier=spec.min_hardware_tier,
                suited_for=list(spec.suited_for),
                llm_calls=spec.llm_calls,
                available=state.available,
                unavailable_reason=state.reason,
                action=state.action,
                warning=state.warning,
                is_default=spec.id == default,
            )
        )
    return StrategiesResponse(default=default, document_id=document_id, strategies=out)


@router.put("/rag/default", response_model=StrategiesResponse)
async def set_default(body: DefaultRequest) -> StrategiesResponse:
    """Sets the workspace default. Takes effect on the next question; nothing restarts."""
    try:
        await set_default_strategy(body.strategy)
    except UnknownStrategyError as exc:
        raise _unknown(exc) from exc
    return await strategies()


@router.post("/rag/strategies/{strategy_id}/prepare", response_model=StartedJob)
async def prepare_strategy(strategy_id: str, body: PrepareRequest) -> StartedJob:
    """Builds what a strategy is missing for a document (its index variant, or the knowledge
    graph) as a background job with real progress."""
    try:
        spec = get_strategy(strategy_id)
    except UnknownStrategyError as exc:
        raise _unknown(exc) from exc
    document = await _document(body.document_id)
    state = await availability.check(spec, document, await availability.llm_state())
    if body.rebuild and spec.plan.graph:
        # Read the graph again from scratch: after a failed first pass, or to pick up a
        # better extraction model.
        state = availability.Availability(available=False, reason=None, action="build_graph")
    if state.action is None:
        raise AppError(
            "nothing_to_prepare",
            "Already available."
            if state.available
            else state.reason or "This cannot be fixed automatically.",
            409 if state.available else 422,
        )

    job = await jobs.create_job(
        "prepare_strategy",
        {"strategy": strategy_id, "document_id": document.id, "action": state.action},
    )

    async def work(ctx: jobs.JobContext) -> dict:
        if state.action == "build_index":
            assert state.variant is not None
            try:
                count = await build_variant(document.id, state.variant, ctx.progress)
            except VariantError as exc:
                raise RuntimeError(exc.message) from exc
            return {"action": "build_index", "variant": state.variant, "chunks": count}

        await ctx.progress(0.05, "Loading the document's chunks")
        async with session_scope() as session:
            rows = (
                (
                    await session.execute(
                        select(ChunkRow).where(
                            ChunkRow.doc_id == document.id, ChunkRow.variant == "default"
                        )
                    )
                )
                .scalars()
                .all()
            )
        chunks = [Chunk(chunk_id=r.chunk_id, doc_id=r.doc_id, text=r.text) for r in rows]
        await ctx.progress(0.1, f"Extracting entities and relations from {len(chunks)} chunks")

        async def relay(fraction: float, message: str) -> None:
            await ctx.progress(0.1 + 0.85 * fraction, message)

        stats = await build_graph_for_document(document.id, chunks, progress=relay)
        get_graph_store().save()
        await ingestion_service.set_graph_counts(document.id, stats["entities"], stats["triples"])
        await ctx.progress(1.0, f"{stats['entities']} entities, {stats['triples']} relations")
        return {"action": "build_graph", **stats}

    jobs.launch(job.id, work)
    return StartedJob(job_id=job.id)


@router.get("/documents/{document_id}/recommendation")
async def recommendation(document_id: str) -> dict:
    """The strategy the rule set recommends for this document, the measured reasons, and the
    full rule trace. Deterministic: the same document always gets the same answer."""
    document = await _document(document_id)
    if document.masked_text is None:
        raise AppError(
            "document_not_ready", f"Document {document_id} has not finished ingestion", 422
        )
    profile = await profiler_service.profile(
        document_id,
        document.masked_text,
        document.language,
        document.ocr_confidence,
        document.page_count,
    )
    result = advisor.recommend(profile)
    llm = await availability.llm_state()
    state = await availability.check(get_strategy(result.recommended), document, llm)
    return {
        "document_id": document_id,
        **result.to_dict(),
        "display_name": get_strategy(result.recommended).display_name,
        "runner_up_display_name": (
            get_strategy(result.runner_up).display_name if result.runner_up else None
        ),
        "available": state.available,
        "unavailable_reason": state.reason,
        "action": state.action,
        "current_default": default_strategy_id(),
        # The graph is built in the background after a document becomes ready; until it has
        # finished, graph-based signals are still zero and the recommendation may change.
        "provisional": document.enrichment_status == "running",
        "features": profile.model_dump(),
    }


@router.post("/rag/compare/estimate")
async def compare_estimate(body: CompareRequest) -> dict:
    await _document(body.document_id)
    try:
        baseline = body.baseline or default_strategy_id()
        ordered = list(dict.fromkeys([baseline, *body.strategies]))
        for strategy_id in ordered:
            get_strategy(strategy_id)
        return await compare.estimate(body.document_id, ordered, body.dataset_id, body.query)
    except UnknownStrategyError as exc:
        raise _unknown(exc) from exc
    except compare.ComparisonError as exc:
        raise AppError(exc.code, exc.message, 422) from exc


@router.post("/rag/compare", response_model=StartedJob)
async def start_comparison(body: CompareRequest) -> StartedJob:
    """Starts the comparison as a background job; its result carries `comparison_id`."""
    await _document(body.document_id)
    if bool(body.dataset_id) == bool(body.query and body.query.strip()):
        raise AppError("invalid_comparison", "Give either an eval set or one question.", 422)
    try:
        for strategy_id in [*body.strategies, *([body.baseline] if body.baseline else [])]:
            get_strategy(strategy_id)
    except UnknownStrategyError as exc:
        raise _unknown(exc) from exc

    job = await jobs.create_job("comparison", body.model_dump())

    async def work(ctx: jobs.JobContext) -> dict:
        try:
            row = await compare.run_comparison(
                body.document_id,
                body.strategies,
                dataset_id=body.dataset_id,
                query=body.query,
                baseline=body.baseline,
                progress=ctx.progress,
                checkpoint=ctx.checkpoint,
            )
        except compare.ComparisonError as exc:
            raise RuntimeError(exc.message) from exc
        return {"comparison_id": row.id}

    jobs.launch(job.id, work)
    return StartedJob(job_id=job.id)


@router.get("/rag/comparisons/{comparison_id}", response_model=ComparisonOut)
async def get_comparison(comparison_id: str) -> ComparisonOut:
    row = await compare.get_comparison(comparison_id)
    if row is None:
        raise AppError("comparison_not_found", f"No comparison with id {comparison_id}", 404)
    return ComparisonOut(
        id=row.id, document_id=row.document_id, created_at=row.created_at, result=row.result
    )


@router.get("/documents/{document_id}/comparisons", response_model=ComparisonListOut)
async def list_comparisons(document_id: str) -> ComparisonListOut:
    """Newest first. Reading these never runs anything."""
    rows = await compare.latest_comparisons(document_id)
    return ComparisonListOut(
        comparisons=[
            ComparisonOut(
                id=r.id, document_id=r.document_id, created_at=r.created_at, result=r.result
            )
            for r in rows
        ]
    )
