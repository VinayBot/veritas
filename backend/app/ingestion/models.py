"""The Document row: one per uploaded file or scraped URL, tracked through the pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512))
    source_type: Mapped[str] = mapped_column(String(16))  # "upload" | "url"
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Real job state machine: queued -> running -> ready | failed | cancelled. "ready" means
    # the critical path (parse..index) is done and the document is chat-able; enrichment_*
    # tracks the slower, non-blocking graph/profile/advisor phase separately.
    status: Mapped[str] = mapped_column(String(32), default="queued")
    current_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    enrichment_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    enrichment_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    raw_text_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_score_before: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score_after: Mapped[float | None] = mapped_column(Float, nullable=True)
    fix_log: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Reported by the parser for paged formats; None for text, HTML and URLs.
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Embedding model the working index was built with — what detects a stale index after
    # the embedding model is changed.
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    pii_counts: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    masked_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    graph_entity_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    graph_triple_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The strategy this document is answered with when a question does not name one: the
    # measured best after upload ("measured"), or one the user picked ("chosen").
    preferred_strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    strategy_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # The automatic strategy measurement after upload: queued | running | done | skipped | failed
    measure_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    measure_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
