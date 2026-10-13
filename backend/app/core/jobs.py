"""Persisted background jobs with progress, cancellation and a resumable event stream.

One mechanism for everything slow that a person starts from the UI: evaluation runs,
strategy comparisons, building an index variant, re-indexing after an embedding-model
change. Modelled on the chat run tracker (app/agents/runs.py): a job is a database row from
the moment it is requested, every progress message is a numbered row, and a client can
reattach to the stream at any time.

Heavy jobs run one at a time on both hardware tiers: they compete for the same local models,
and two at once would only make both slower. A job that has to wait says so ("queued").
Concurrency *inside* a job (how many strategies run side by side) is the job's own decision
and is where the tier matters.

Cancellation is cooperative: `JobContext.checkpoint()` raises at the next safe point, and
the task is also cancelled so an in-flight await stops promptly.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, session_scope

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 0.3
TERMINAL_STATUSES = ("done", "failed", "cancelled")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(32))
    data: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class JobCancelled(Exception):
    pass


_tasks: dict[str, asyncio.Task[None]] = {}
_cancel_requested: set[str] = set()
_gates: dict[int, asyncio.Semaphore] = {}


def _gate() -> asyncio.Semaphore:
    # One semaphore per event loop: a primitive created on one loop cannot be awaited from
    # another, and the test suite runs each test on a fresh loop.
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _gates:
        _gates[loop_id] = asyncio.Semaphore(1)
    return _gates[loop_id]


class JobContext:
    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self._seq = 0

    def checkpoint(self) -> None:
        if self.job_id in _cancel_requested:
            raise JobCancelled()

    async def emit(self, event: str, data: Any) -> None:
        seq = self._seq
        self._seq += 1
        async with session_scope() as session:
            session.add(
                JobEvent(
                    job_id=self.job_id,
                    seq=seq,
                    event=event,
                    data=data,
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

    async def progress(self, fraction: float, message: str, **extra: Any) -> None:
        """`fraction` is work actually completed (0..1), never an estimate of time."""
        self.checkpoint()
        fraction = max(0.0, min(1.0, fraction))
        await _update(self.job_id, progress=fraction, message=message)
        await self.emit("progress", {"progress": fraction, "message": message, **extra})


async def _update(job_id: str, **fields: Any) -> None:
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        job.updated_at = datetime.now(UTC)
        await session.commit()


async def create_job(kind: str, params: dict[str, Any]) -> Job:
    now = datetime.now(UTC)
    job = Job(
        id=str(uuid.uuid4()),
        kind=kind,
        status="queued",
        params=params,
        progress=0.0,
        message="Queued",
        created_at=now,
        updated_at=now,
    )
    async with session_scope() as session:
        session.add(job)
        await session.commit()
    return job


async def get_job(job_id: str) -> Job | None:
    async with session_scope() as session:
        return await session.get(Job, job_id)


async def list_jobs(
    kind: str | None = None, active_only: bool = False, limit: int = 20
) -> list[Job]:
    async with session_scope() as session:
        query = select(Job).order_by(Job.created_at.desc()).limit(limit)
        if kind:
            query = query.where(Job.kind == kind)
        if active_only:
            query = query.where(Job.status.not_in(TERMINAL_STATUSES))
        return list((await session.execute(query)).scalars().all())


async def _run(job_id: str, work: Callable[[JobContext], Awaitable[dict[str, Any] | None]]) -> None:
    from app.llm.client import mark_background

    mark_background()  # a background job never makes a chat answer wait for the model
    ctx = JobContext(job_id)
    try:
        if _gate().locked():
            await ctx.emit(
                "progress", {"progress": 0.0, "message": "Waiting for another job to finish"}
            )
            await _update(job_id, message="Waiting for another job to finish")
        async with _gate():
            ctx.checkpoint()
            await _update(job_id, status="running", message="Starting")
            await ctx.emit("status", {"status": "running"})
            result = await work(ctx)
        await _update(job_id, status="done", progress=1.0, message="Done", result=result or {})
        await ctx.emit("done", {"result": result or {}})
    except (JobCancelled, asyncio.CancelledError):
        await _update(job_id, status="cancelled", message="Cancelled")
        await ctx.emit("cancelled", {})
    except Exception as exc:  # noqa: BLE001 — a job failing must surface as a status, not vanish
        logger.exception("Job %s failed", job_id)
        message = f"{type(exc).__name__}: {exc}"[:1000]
        await _update(job_id, status="failed", error=message, message="Failed")
        await ctx.emit("error", {"message": message})
    finally:
        _cancel_requested.discard(job_id)
        _tasks.pop(job_id, None)


def launch(job_id: str, work: Callable[[JobContext], Awaitable[dict[str, Any] | None]]) -> None:
    """Runs `work` as a task that outlives the request that started it."""
    _tasks[job_id] = asyncio.ensure_future(_run(job_id, work))


async def cancel(job_id: str) -> str:
    """Returns the job's status after the request: "cancelling" if it was still running."""
    job = await get_job(job_id)
    if job is None:
        raise KeyError(job_id)
    if job.status in TERMINAL_STATUSES:
        return job.status
    _cancel_requested.add(job_id)
    task = _tasks.get(job_id)
    if task is not None and not task.done():
        task.cancel()
        return "cancelling"
    # No task in this process (it was started before a restart): settle it directly.
    await _update(job_id, status="cancelled", message="Cancelled")
    return "cancelled"


async def wait(job_id: str, timeout: float = 600.0) -> Job:
    """Blocks until the job is terminal. For scripts and tests; the UI uses the stream."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        job = await get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status in TERMINAL_STATUSES:
            return job
        if asyncio.get_running_loop().time() > deadline:
            raise TimeoutError(f"job {job_id} still {job.status} after {timeout}s")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def stream(job_id: str, after_seq: int = -1) -> AsyncIterator[JobEvent]:
    """Replays persisted events with seq > after_seq, then follows until a terminal one."""
    seen = after_seq
    while True:
        async with session_scope() as session:
            rows = (
                (
                    await session.execute(
                        select(JobEvent)
                        .where(JobEvent.job_id == job_id, JobEvent.seq > seen)
                        .order_by(JobEvent.seq)
                    )
                )
                .scalars()
                .all()
            )
        for row in rows:
            seen = row.seq
            yield row
            if row.event in ("done", "error", "cancelled"):
                return
        job = await get_job(job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


async def reconcile_orphaned_jobs() -> int:
    """At startup: a job still queued or running belongs to a process that no longer exists."""
    async with session_scope() as session:
        rows = (
            (await session.execute(select(Job).where(Job.status.not_in(TERMINAL_STATUSES))))
            .scalars()
            .all()
        )
        for job in rows:
            job.status = "failed"
            job.error = "Interrupted by a backend restart before it finished. Start it again."
            job.message = "Interrupted"
            job.updated_at = datetime.now(UTC)
        await session.commit()
        return len(rows)
