"""Trace event schema shared by every pipeline stage, the WebSocket feed, and the audit log.

Every real pipeline action emits one of these. The Architecture tab's animations are driven
exclusively by this stream — nothing in the frontend is allowed to synthesize a pulse from a timer.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TraceStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    BLOCKED = "blocked"
    ERROR = "error"
    RETRYING = "retrying"


class TraceEvent(BaseModel):
    trace_id: str
    session_id: str
    seq: int = 0
    """Strictly increasing per session_id, assigned by TraceBus.publish() — never by the
    caller. This is what makes replay deterministic (UI state is a pure function of the
    ordered event list) and lets a client de-duplicate/detect gaps instead of trusting
    arrival order, which a reconnect or a slow consumer can't otherwise guarantee."""
    stage: str
    status: TraceStatus
    started_at: datetime
    duration_ms: float | None = None
    from_stage: str | None = None
    to_stage: str | None = None
    input_preview: str | None = None
    output_preview: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
