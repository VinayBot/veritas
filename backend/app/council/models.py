"""Persistence for one LLM Council run — every member's raw answer, every peer-review score,
and the chairman's synthesis, so the Model Selection Arena UI (Phase 11) can replay a past run
in full rather than only ever seeing the final answer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class CouncilRun(Base):
    __tablename__ = "council_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    query: Mapped[str] = mapped_column(Text)
    members: Mapped[list[str]] = mapped_column(JSON)
    chairman_model: Mapped[str] = mapped_column(String(128))
    member_answers: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    peer_reviews: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    agreement_score: Mapped[float] = mapped_column(Float)
    final_answer: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
