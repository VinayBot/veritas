from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GenerateDatasetRequest(BaseModel):
    target_size: int = Field(default=20, ge=5, le=60)


class GenerateDatasetResponse(BaseModel):
    dataset_id: str
    document_id: str
    version: int
    item_count: int
    categories: dict[str, int]


class DatasetOut(BaseModel):
    id: str
    document_id: str
    version: int
    item_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class DatasetListResponse(BaseModel):
    datasets: list[DatasetOut]


class RunBenchmarkRequest(BaseModel):
    document_id: str
    """Strategy ids from GET /rag/strategies. Omitted = the default set."""
    configs: list[str] | None = None
    """An existing eval set to run against. Omitted = the document's latest, or a new one of
    `dataset_target_size` questions if it has none."""
    dataset_id: str | None = None
    dataset_target_size: int = Field(default=10, ge=5, le=40)
    include_safety: bool = True


class ConfigResultOut(BaseModel):
    name: str
    retrieval_metrics: dict[str, float]
    """None = not measured. Old runs always carry a number here; see `harness_version`."""
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    correctness: float | None = None
    citation_validity: float | None = None
    p50_latency_ms: float
    p95_latency_ms: float
    n_samples: int
    n_judged: dict[str, int] = {}
    avg_prompt_tokens: float | None = None
    avg_completion_tokens: float | None = None
    avg_llm_calls: float | None = None
    production_score: float | None = None
    passes_hard_gates: bool
    gate_failures: list[str] = []
    skipped_reason: str | None = None
    samples: list[dict[str, Any]] = []


class BenchmarkRunResponse(BaseModel):
    id: str
    document_id: str
    created_at: datetime
    config_results: list[ConfigResultOut]
    injection_block_rate: float | None
    pii_leak_count: int | None
    recommended_config: str | None
    """2 for runs from the current harness. None marks a run from the first harness, whose
    scores were computed differently and must not be compared with later runs."""
    harness_version: int | None = None
    dataset_id: str | None = None
    dataset_version: int | None = None
    n_items: int | None = None
    run_config: dict[str, Any] | None = None
    duration_ms: float | None = None


class BenchmarkRunListResponse(BaseModel):
    """Oldest-first run history."""

    runs: list[BenchmarkRunResponse]


class StartedJob(BaseModel):
    job_id: str
