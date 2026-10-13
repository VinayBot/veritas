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
    # Provenance of the run. NULL on rows written by the first harness, whose numbers are not
    # comparable with later ones (see app/evaluation/benchmark.py's module docstring).
    harness_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dataset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    dataset_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_items: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # {"judge", "generator", "embedding", "reranker", "chunking"} at the time of the run.
    run_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class StrategyEvaluation(Base):
    """One strategy's measured result on one eval set over one state of the corpus — the
    unit comparisons are assembled from, and the cache that keeps reopening a comparison from
    re-running anything. `cache_key` covers everything that could change the numbers."""

    __tablename__ = "strategy_evaluations"

    cache_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    strategy: Mapped[str] = mapped_column(String(32))
    dataset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    corpus_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    run_config: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class ComparisonRun(Base):
    __tablename__ = "comparison_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    dataset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    strategies: Mapped[list[str]] = mapped_column(JSON)
    baseline: Mapped[str] = mapped_column(String(32))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime)
