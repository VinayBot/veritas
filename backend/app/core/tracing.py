"""In-process trace bus: pipeline stages publish TraceEvents, the /ws/trace/{session_id}
route and the SQLite audit log subscribe. No timers, no synthetic events — every event here
corresponds to a real stage execution.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from app.core.events import TraceEvent, TraceStatus


class TraceBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[TraceEvent]]] = {}
        self._history: dict[str, list[TraceEvent]] = {}
        self._next_seq: dict[str, int] = {}

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
