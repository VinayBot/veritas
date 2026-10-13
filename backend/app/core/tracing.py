"""In-process trace bus: pipeline stages publish TraceEvents, the /ws/trace/{session_id}
route and the SQLite audit log subscribe. No timers, no synthetic events — every event here
corresponds to a real stage execution.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from app.core.events import TraceEvent, TraceStatus

_TERMINAL = (TraceStatus.DONE, TraceStatus.ERROR, TraceStatus.BLOCKED)
STATS_WINDOW = 200
RECENT_EVENTS_PER_STAGE = 10


class StageStats:
    """Rolling, in-memory figures for one stage name across every session since the process
    started — what the Architecture tab shows per node. Nothing here survives a restart, and
    the API says so ("since backend start") rather than implying a longer history."""

    def __init__(self) -> None:
        self.count = 0
        self.errors = 0
        self.blocked = 0
        self.last_duration_ms: float | None = None
        self.last_status: str | None = None
        self.last_at: datetime | None = None
        self.durations: deque[float] = deque(maxlen=STATS_WINDOW)

    def percentile(self, p: float) -> float | None:
        if not self.durations:
            return None
        ordered = sorted(self.durations)
        return ordered[min(int(len(ordered) * p), len(ordered) - 1)]

    def to_dict(self) -> dict:
        return {
            "invocation_count": self.count,
            "error_count": self.errors,
            "blocked_count": self.blocked,
            "last_latency_ms": self.last_duration_ms,
            "last_status": self.last_status,
            "last_at": self.last_at.isoformat() if self.last_at else None,
            "p50_latency_ms": self.percentile(0.5),
            "p95_latency_ms": self.percentile(0.95),
            "sample_size": len(self.durations),
        }


class TraceBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[TraceEvent]]] = {}
        self._history: dict[str, list[TraceEvent]] = {}
        self._next_seq: dict[str, int] = {}
        self._stats: dict[str, StageStats] = {}
        self._recent: dict[str, deque[TraceEvent]] = {}
        self.started_at = datetime.now(UTC)

    def stage_stats(self) -> dict[str, StageStats]:
        return dict(self._stats)

    def recent_events(
        self, stages: list[str], limit: int = RECENT_EVENTS_PER_STAGE
    ) -> list[TraceEvent]:
        """Newest first, across the given stage names."""
        merged = [e for stage in stages for e in self._recent.get(stage, ())]
        merged.sort(key=lambda e: e.started_at, reverse=True)
        return merged[:limit]

    def subscriber_count(self) -> int:
        return sum(len(queues) for queues in self._subscribers.values())

    def session_count(self) -> int:
        return len(self._history)

    def _record(self, event: TraceEvent) -> None:
        if event.status not in _TERMINAL:
            return
        stats = self._stats.setdefault(event.stage, StageStats())
        stats.count += 1
        stats.last_status = str(event.status)
        stats.last_at = datetime.now(UTC)
        if event.status == TraceStatus.ERROR:
            stats.errors += 1
        if event.status == TraceStatus.BLOCKED:
            stats.blocked += 1
        if event.duration_ms is not None:
            stats.last_duration_ms = event.duration_ms
            stats.durations.append(event.duration_ms)
        self._recent.setdefault(event.stage, deque(maxlen=RECENT_EVENTS_PER_STAGE)).append(event)

    def subscribe(self, session_id: str) -> asyncio.Queue[TraceEvent]:
        queue: asyncio.Queue[TraceEvent] = asyncio.Queue()
        self._subscribers.setdefault(session_id, []).append(queue)
        return queue

    def unsubscribe(self, session_id: str, queue: asyncio.Queue[TraceEvent]) -> None:
        subs = self._subscribers.get(session_id, [])
        if queue in subs:
            subs.remove(queue)

    def history(self, session_id: str) -> list[TraceEvent]:
        return list(self._history.get(session_id, []))

    async def publish(self, event: TraceEvent) -> None:
        # The single funnel every event passes through — assigning `seq` here, rather than
        # trusting each call site to know the right next number, is what guarantees a strict,
        # gap-free, per-session order regardless of how many concurrent stages are publishing.
        seq = self._next_seq.get(event.session_id, 0)
        self._next_seq[event.session_id] = seq + 1
        event.seq = seq
        self._history.setdefault(event.session_id, []).append(event)
        self._record(event)
        for queue in self._subscribers.get(event.session_id, []):
            await queue.put(event)

    @asynccontextmanager
    async def stage(
        self,
        session_id: str,
        stage: str,
        from_stage: str | None = None,
        to_stage: str | None = None,
        input_preview: str | None = None,
    ) -> AsyncIterator[StageHandle]:
        trace_id = str(uuid.uuid4())
        started_at = datetime.now(UTC)
        start_perf = time.perf_counter()
        await self.publish(
            TraceEvent(
                trace_id=trace_id,
                session_id=session_id,
                stage=stage,
                status=TraceStatus.RUNNING,
                started_at=started_at,
                from_stage=from_stage,
                to_stage=to_stage,
                input_preview=input_preview,
            )
        )
        handle = StageHandle(trace_id)
        try:
            yield handle
        except Exception as exc:
            await self.publish(
                TraceEvent(
                    trace_id=trace_id,
                    session_id=session_id,
                    stage=stage,
                    status=TraceStatus.ERROR,
                    started_at=started_at,
                    duration_ms=(time.perf_counter() - start_perf) * 1000,
                    from_stage=from_stage,
                    to_stage=to_stage,
                    output_preview=str(exc)[:500],
                    metrics=handle.metrics,
                )
            )
            raise
        else:
            await self.publish(
                TraceEvent(
                    trace_id=trace_id,
                    session_id=session_id,
                    stage=stage,
                    status=TraceStatus.BLOCKED if handle.blocked else TraceStatus.DONE,
                    started_at=started_at,
                    duration_ms=(time.perf_counter() - start_perf) * 1000,
                    from_stage=from_stage,
                    to_stage=to_stage,
                    output_preview=handle.output_preview,
                    metrics=handle.metrics,
                )
            )


class StageHandle:
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self.metrics: dict[str, object] = {}
        self.output_preview: str | None = None
        self.blocked = False

    def set_output(self, preview: str) -> None:
        self.output_preview = preview[:500]

    def set_metric(self, key: str, value: object) -> None:
        self.metrics[key] = value

    def mark_blocked(self) -> None:
        self.blocked = True


trace_bus = TraceBus()
