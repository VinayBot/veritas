"""Persistence for the synthetic eval datasets, advisor recommendations, and benchmark runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EvalDataset(Base):
    __tablename__ = "eval_datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(1024))
    item_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class AdvisorRecommendation(Base):
    __tablename__ = "advisor_recommendations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    baseline_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    suggested_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    baseline_metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    suggested_metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    gain_ndcg: Mapped[float] = mapped_column(Float)
    rationale: Mapped[list[str]] = mapped_column(JSON)
    suggested_mode: Mapped[str] = mapped_column(String(16))
    mode_reason: Mapped[str] = mapped_column(Text)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    config_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    production_recommendation: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
