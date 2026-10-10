"""The per-chat-turn report, including the real Estimated quality metrics (Phase 8) computed
by the LLM judge against the actual answer and citations — reference-free, since a live chat
turn has no ground truth to verify against (that's what the benchmark runner's "Verified"
scores are for; see app/evaluation/judge.py)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


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
