"""Persisted chat-run tracking (Fix 1 — see docs/DECISIONS.md).

Before this, a chat turn's only state was a plain asyncio Task referenced from inside the one
HTTP request that started it, and its only progress feed was `trace_bus` — an in-process,
per-session pub/sub with no durable history. A dropped connection or a backend restart lost
all visibility into a turn that might still be running (or that finished but was never
delivered). This module adds the missing persisted half: every question becomes a `ChatRun`
row (`queued -> planning/retrieving/generating/verifying -> done/failed/abstained/blocked/
cancelled`) the instant it's asked, and every SSE frame it ever emits is durably logged as a
numbered `ChatRunEvent`, so `GET /api/v1/runs/{id}` can report status at any time and a client
can reattach an SSE stream after a drop via `after_seq` (the frontend's Last-Event-ID
equivalent) without losing or duplicating anything.

Design choice: `stream_run` (the consumer side, used by every SSE response) is pure DB
polling — no `trace_bus` coupling, no shared asyncio.Queue between producer and consumer. This
makes it trivial for multiple readers to reattach to the same run independently (each just
tracks its own `seen_seq` cursor) and immune to a backend restart losing a live subscription
mid-stream (there's nothing live to lose; everything a reader needs is already a row).
`_relay_trace_to_run` is the one place that *does* subscribe to `trace_bus`, as the sole
producer translating real stage transitions into persisted, numbered events — this relies on
at most one run being active per session_id at a time (true today — nothing fires a second
turn on the same conversation before the first finishes); revisit if concurrent same-session
runs become real.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.agents.models import TERMINAL_RUN_STATUSES, ChatRun, ChatRunEvent
from app.core.db import session_scope
from app.core.events import TraceStatus
from app.core.tracing import trace_bus

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 0.3
# How often an open answer stream looks for new frames; short, so tokens arrive as written.
STREAM_POLL_SECONDS = 0.08
_record_locks: dict[str, asyncio.Lock] = {}

_STAGE_TO_STATUS: dict[str, str] = {
    "guardian_in": "planning",
    "planner": "planning",
    "decline": "generating",
    "rewriter": "retrieving",
    "retriever": "retrieving",
    "critic": "retrieving",
    "summarizer": "generating",
    "synthesizer": "generating",
    "verifier": "verifying",
    "guardian_out": "verifying",
    "semantic_cache": "generating",
    "council": "generating",
    "retry": "generating",
}

# A strong reference to every in-flight background task, keyed by run_id. asyncio does not
# guarantee a task survives once nothing holds a reference to it (`asyncio.create_task` result
# discarded == eligible for GC mid-flight, a documented gotcha) — this dict is that reference.
# Each task removes its own entry on completion via add_done_callback.
_in_flight: dict[str, asyncio.Task] = {}


async def create_run(
    run_id: str, session_id: str, document_id: str | None, mode: str, query: str
) -> None:
    now = datetime.now(UTC)
    async with session_scope() as session:
        session.add(
            ChatRun(
                id=run_id,
                session_id=session_id,
                document_id=document_id,
                mode=mode,
                query=query,
                status="queued",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()


async def _next_seq(run_id: str) -> int:
    async with session_scope() as session:
        result = await session.execute(
            select(ChatRunEvent.seq)
            .where(ChatRunEvent.run_id == run_id)
            .order_by(ChatRunEvent.seq.desc())
            .limit(1)
        )
        last = result.scalar_one_or_none()
    return (last + 1) if last is not None else 0


async def record_event(run_id: str, event: str, data: Any) -> int:
    """Persists one SSE frame's data and returns its seq. Does not itself yield SSE text —
    callers (chat.py's route, run_chat_turn_tracked) format and send that part; this only owns
    the durable record."""
    # The stage relay and the token stream record concurrently; seq must stay unique.
    lock = _record_locks.setdefault(run_id, asyncio.Lock())
    async with lock:
        seq = await _next_seq(run_id)
        async with session_scope() as session:
            session.add(
                ChatRunEvent(
                    run_id=run_id, seq=seq, event=event, data=data, created_at=datetime.now(UTC)
                )
            )
            await session.commit()
    if event in ("done", "error"):
        _record_locks.pop(run_id, None)
    return seq


async def set_run_status(
    run_id: str,
    status: str,
    *,
    stage: str | None = None,
    error: str | None = None,
    report_id: str | None = None,
    attempt: int | None = None,
) -> None:
    async with session_scope() as session:
        run = await session.get(ChatRun, run_id)
        if run is None:
            logger.warning("set_run_status: unknown run_id %r", run_id)
            return
        run.status = status
        run.updated_at = datetime.now(UTC)
        if stage is not None:
            run.stage = stage
        if error is not None:
            run.error = error
        if report_id is not None:
            run.report_id = report_id
        if attempt is not None:
            run.attempt = attempt
        await session.commit()


async def get_run(run_id: str) -> ChatRun | None:
    async with session_scope() as session:
        return await session.get(ChatRun, run_id)


async def get_events_since(run_id: str, after_seq: int) -> list[ChatRunEvent]:
    async with session_scope() as session:
        result = await session.execute(
            select(ChatRunEvent)
            .where(ChatRunEvent.run_id == run_id, ChatRunEvent.seq > after_seq)
            .order_by(ChatRunEvent.seq)
        )
        return list(result.scalars().all())


def launch_run(run_id: str, coro) -> asyncio.Task:
    """Schedules `coro` as a background task that outlives the HTTP request/response cycle
    that created it, keeping a strong reference (see module docstring) so it survives even if
    the client disconnects immediately."""
    task = asyncio.ensure_future(coro)
    _in_flight[run_id] = task
    task.add_done_callback(lambda _t: _in_flight.pop(run_id, None))
    return task


def get_in_flight_task(run_id: str) -> asyncio.Task | None:
    return _in_flight.get(run_id)


async def relay_trace_to_run(run_id: str, session_id: str, stop_event: asyncio.Event) -> None:
    """The one producer that subscribes to trace_bus: translates each real stage-started
    TraceEvent for this session into a persisted, numbered `stage` ChatRunEvent and updates the
    run's coarse status. Polls `stop_event` rather than blocking forever on `queue.get()` so it
    exits promptly once the pipeline finishes, even if no further trace event ever arrives."""
    queue = trace_bus.subscribe(session_id)
    try:
        while not stop_event.is_set():
            try:
                trace_event = await asyncio.wait_for(queue.get(), timeout=POLL_INTERVAL_SECONDS)
            except TimeoutError:
                continue
            if trace_event.status != TraceStatus.RUNNING:
                continue
            status = _STAGE_TO_STATUS.get(trace_event.stage, "generating")
            await record_event(run_id, "stage", {"stage": trace_event.stage, "status": status})
            await set_run_status(run_id, status, stage=trace_event.stage)
    finally:
        trace_bus.unsubscribe(session_id, queue)


async def stream_run(run_id: str, after_seq: int = -1) -> AsyncIterator[ChatRunEvent]:
    """Pure DB polling, no trace_bus involved — see module docstring for why. Replays anything
    already persisted with seq > after_seq, then, if the run is still active, keeps polling for
    more until a terminal event (done/error) or the run's own status reaches a terminal value."""
    seen_seq = after_seq
    while True:
        events = await get_events_since(run_id, seen_seq)
        for ev in events:
            seen_seq = ev.seq
            yield ev
            if ev.event in ("done", "error"):
                return

        run = await get_run(run_id)
        if run is None:
            return
        if run.status in TERMINAL_RUN_STATUSES:
            # Terminal but the loop above found nothing new this pass — either the final event
            # was already yielded in a prior iteration (and we'd have returned above), or this
            # run reached a terminal status without ever recording a done/error event (should
            # not happen at any real call site, but don't poll forever over a bug elsewhere).
            return

        await asyncio.sleep(STREAM_POLL_SECONDS)


async def reconcile_interrupted_runs() -> int:
    """Run once at startup, mirroring app/ingestion/service.py's reconcile_interrupted_jobs: an
    in-memory asyncio task (including this module's own _in_flight registry) doesn't survive a
    process restart, so any run still in a non-terminal status from a previous process lifetime
    is permanently stuck with nothing left to ever update it. Marks each one "failed" with a
    clear reason instead of leaving a client polling or reattached to it forever. Returns the
    count fixed, for the startup log."""
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(ChatRun).where(ChatRun.status.not_in(TERMINAL_RUN_STATUSES))
                )
            )
            .scalars()
            .all()
        )
        for run in rows:
            run.status = "failed"
            run.error = (
                "This run was interrupted by a backend restart before it finished. "
                "Please retry the question."
            )
            run.updated_at = datetime.now(UTC)
        await session.commit()
        return len(rows)
