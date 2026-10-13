from __future__ import annotations

from pydantic import BaseModel, Field


class GenerateDatasetRequest(BaseModel):
    target_size: int = Field(default=20, ge=5, le=60)


class GenerateDatasetResponse(BaseModel):
    dataset_id: str
    document_id: str
    version: int
    item_count: int
    categories: dict[str, int]


class RunBenchmarkRequest(BaseModel):
    document_id: str
    configs: list[str] | None = None
    dataset_target_size: int = Field(default=10, ge=5, le=40)


class ConfigResultOut(BaseModel):
    name: str
    retrieval_metrics: dict[str, float]
    faithfulness: float
    correctness: float
    citation_validity: float
    p50_latency_ms: float
    p95_latency_ms: float
    n_samples: int
    production_score: float
    passes_hard_gates: bool


class BenchmarkRunResponse(BaseModel):
    id: str
    document_id: str
    config_results: list[ConfigResultOut]
    injection_block_rate: float
    pii_leak_count: int
    recommended_config: str | None


class BenchmarkRunListResponse(BaseModel):
    """Oldest-first run history for one document (EV-4's by-run chart, EV-3's delta vs the
    previous run) — additive, read-only, built on the already-persisted BenchmarkRun rows."""

    runs: list[BenchmarkRunResponse]
