"""Which strategy answers a document, and measuring it automatically after upload.

Every document can carry its own strategy. After upload the app measures a few strategies on
questions with known answers written from that document, and the highest scorer becomes the
document's strategy ("measured"). The user can pick another ("chosen"), which a later
automatic measurement never overrides. A document with neither uses the workspace default.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import get_settings
from app.core.db import session_scope
from app.ingestion.models import Document
from app.rag_engines.registry import STRATEGIES, default_strategy_id, get_strategy

logger = logging.getLogger(__name__)

# Fast, direct strategies that cover the main retrieval styles. The agent and the council are
# slower by an order of magnitude and are left to an explicit comparison.
AUTO_CANDIDATES = ("hybrid", "hybrid_rerank", "graph_rag")
AUTO_QUESTIONS = 5


class _NewestFirst:
    """One measurement at a time, and when several are waiting the most recent upload goes
    next: that is the document the user is looking at. State lives per event loop."""

    def __init__(self) -> None:
        self.cond = asyncio.Condition()
        self.pending: set[int] = set()
        self.running = False
        self.seq = 0


_queues: dict[int, _NewestFirst] = {}


def _queue() -> _NewestFirst:
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _queues:
        _queues.clear()  # a new loop (tests): drop state bound to the old one
        _queues[loop_id] = _NewestFirst()
    return _queues[loop_id]


@asynccontextmanager
async def _no_slot() -> AsyncIterator[None]:
    yield


@asynccontextmanager
async def _measure_slot() -> AsyncIterator[None]:
    queue = _queue()
    async with queue.cond:
        queue.seq += 1
        ticket = queue.seq
        queue.pending.add(ticket)
        try:
            await queue.cond.wait_for(lambda: not queue.running and ticket == max(queue.pending))
        finally:
            queue.pending.discard(ticket)
        queue.running = True
    try:
        yield
    finally:
        async with queue.cond:
            queue.running = False
            queue.cond.notify_all()


async def effective_strategy(document_id: str | None) -> tuple[str, str]:
    """(strategy id, where it came from: "measured" | "chosen" | "default")."""
    if document_id:
        async with session_scope() as session:
            doc = await session.get(Document, document_id)
        if doc is not None and doc.preferred_strategy in STRATEGIES:
            return doc.preferred_strategy, doc.strategy_source or "measured"
    return default_strategy_id(), "default"


async def _update(document_id: str, **fields: Any) -> None:
    async with session_scope() as session:
        doc = await session.get(Document, document_id)
        if doc is None:
            return
        for key, value in fields.items():
            setattr(doc, key, value)
        await session.commit()


def automatic_choice(measured: dict[str, Any] | None) -> str | None:
    """The strategy a document switches to by itself: the best measured one that answers
    directly. The agent and the council take 15-40 s per answer on this hardware against
    4-7 s, so when one of them measures best it is recommended, and the user switches to it
    with one click, but chat does not silently become several times slower."""
    if not measured:
        return None
    for entry in measured.get("ranking", []):
        strategy = entry.get("strategy")
        if strategy in STRATEGIES and get_strategy(strategy).kind != "agentic":
            return strategy
    return None


async def adopt_measured(document_id: str, strategy: str) -> None:
    """The measured best becomes the document's strategy unless the user chose one."""
    async with session_scope() as session:
        doc = await session.get(Document, document_id)
        if doc is None or doc.strategy_source == "chosen":
            return
        doc.preferred_strategy = strategy
        doc.strategy_source = "measured"
        await session.commit()


async def set_document_strategy(document_id: str, strategy: str | None) -> None:
    """The user's own choice for this document; None hands it back to measurement."""
    if strategy is not None:
        get_strategy(strategy)  # raises UnknownStrategyError
    if strategy is None:
        await _update(document_id, preferred_strategy=None, strategy_source=None)
        return
    await _update(document_id, preferred_strategy=strategy, strategy_source="chosen")


async def auto_measure(document_id: str, *, requested: bool = False) -> dict[str, Any] | None:
    """Measures the candidate strategies that can run on this document and makes the best
    one the document's strategy, unless the user has already chosen one. Returns the
    evidence it decided on, or None when there was nothing to compare."""
    # Imported here: these modules import the orchestrator, which imports this package.
    from app.evaluation import service as evaluation_service
    from app.evaluation.datasets import names_excerpts
    from app.llm import client as llm_client
    from app.rag_engines import availability, compare, evidence

    # After an upload this is housekeeping and yields to everything. When the user asked for
    # it (the Re-measure button, which runs it as a job) it keeps the job's priority: as
    # housekeeping it would wait on every model call for the very job it is running in.
    if not requested:
        llm_client.mark_background(llm_client.HOUSEKEEPING)
    await _update(document_id, measure_status="queued", measure_error=None)
    # Automatic measurements take turns, newest upload first. One the user asked for does not
    # queue: the automatic one running yields to it at every model call (job priority), and
    # queueing it behind uploads that keep arriving could keep it waiting indefinitely.
    async with _measure_slot() if not requested else _no_slot():
        await _update(document_id, measure_status="running")
        try:
            async with session_scope() as session:
                doc = await session.get(Document, document_id)
            if doc is None:
                return None
            llm = await availability.llm_state()
            candidates = [
                s
                for s in AUTO_CANDIDATES
                if (await availability.check(get_strategy(s), doc, llm)).available
            ]
            if len(candidates) < 2:
                await _update(
                    document_id,
                    measure_status="skipped",
                    measure_error="Fewer than two strategies can run on this document.",
                )
                return None
            datasets = [
                d
                for d in await evaluation_service.list_datasets(document_id)
                if not names_excerpts(d.path)
            ]
            dataset = (
                datasets[0]
                if datasets
                else await evaluation_service.generate_and_save_dataset(document_id, AUTO_QUESTIONS)
            )
            await compare.run_comparison(
                document_id, candidates[1:], dataset_id=dataset.id, baseline=candidates[0]
            )
            measured = await evidence.measured_evidence(document_id)
            async with session_scope() as session:
                doc = await session.get(Document, document_id)
                if doc is None:
                    return measured
                choice = automatic_choice(measured)
                if choice is not None and doc.strategy_source != "chosen":
                    doc.preferred_strategy = choice
                    doc.strategy_source = "measured"
                doc.measure_status = "done"
                await session.commit()
            return measured
        except asyncio.CancelledError:
            await _update(document_id, measure_status="failed", measure_error="Stopped.")
            raise
        except Exception as exc:  # noqa: BLE001 — optional work; recorded, never fatal
            logger.warning("Automatic strategy measurement failed for %s: %s", document_id, exc)
            await _update(
                document_id,
                measure_status="failed",
                measure_error=(str(exc) or type(exc).__name__)[:500],
            )
            return None


def auto_measure_enabled() -> bool:
    return get_settings().auto_measure_enabled


async def reconcile_interrupted_measurements() -> int:
    """Run once at startup. A measurement is an in-memory task; one that was queued or running
    when the server stopped will never finish, and its document would show "measuring" for
    ever. They are marked as interrupted so the card offers to measure again."""
    from sqlalchemy import update

    async with session_scope() as session:
        result = await session.execute(
            update(Document)
            .where(Document.measure_status.in_(("queued", "running")))
            .values(measure_status="failed", measure_error="Interrupted by a server restart.")
        )
        await session.commit()
    return result.rowcount or 0
