"""The per-chat-turn report, including the real Estimated quality metrics (Phase 8) computed
by the LLM judge against the actual answer and citations — reference-free, since a live chat
turn has no ground truth to verify against (that's what the benchmark runner's "Verified"
scores are for; see app/evaluation/judge.py).

Also: ChatRun/ChatRunEvent (Fix 1 — see docs/DECISIONS.md), the persisted run state machine
ChatReport never had. ChatReport is a terminal, single-write record of a *finished* turn's
quality metrics; ChatRun is a row that exists from the moment a question is asked and is
updated as it progresses, so a client can poll or reattach to find out whether a turn is still
running, what stage it's on, or why it failed — none of which was previously knowable from
outside the single open HTTP connection that started the turn.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Deliberately coarser than the agent graph's node names (guardian_in, rewriter, critic, ...) —
# this is the user-facing vocabulary a frontend status chip renders, not an internal trace.
RUN_STATUSES = (
    "queued",
    "planning",
    "retrieving",
    "generating",
    "verifying",
    "done",
    "failed",
    "abstained",
    "blocked",
    "cancelled",
)
TERMINAL_RUN_STATUSES = ("done", "failed", "abstained", "blocked", "cancelled")


class ChatReport(Base):
    __tablename__ = "chat_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64))
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    mode: Mapped[str] = mapped_column(String(16))
    query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    agent_steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    quality: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    council_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    routing: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ChatRun(Base):
    __tablename__ = "chat_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64))
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    mode: Mapped[str] = mapped_column(String(16))
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ChatRunEvent(Base):
    """One row per SSE frame a run has ever emitted, in order. The durable half of resume: a
    client reconnecting with Last-Event-ID replays everything with seq > that value from here
    before (if the run is still active) switching to the live trace_bus feed for the rest."""

    __tablename__ = "chat_run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(32))
    data: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
