from __future__ import annotations

from pydantic import BaseModel

from app.profiler.features import DocumentProfile


class ProfileResponse(DocumentProfile):
    """Every measured feature of a document — see app/profiler/features.py for what each is
    computed from."""


class CandidateResultOut(BaseModel):
    name: str
    chunking_strategy: str
    chunking_kwargs: dict
    rerank: bool
    llm_model: str | None
    retrieval_metrics: dict[str, float]
    faithfulness: float
    avg_latency_ms: float
    index_size: int
    composite_score: float
    n_samples: int = 0


class AdvisorResponse(BaseModel):
    document_id: str
    baseline: CandidateResultOut
    suggested: CandidateResultOut
    gain_ndcg_points: float
    rationale: list[str]
    suggested_mode: str
    mode_reason: str
    decision: str | None
    """Every tournament candidate (not just baseline/winner) — additive: existing callers
    that only read baseline/suggested are unaffected. The Evaluation page's chunking-strategy
    table uses this to show all 6 real strategies, not just 2."""
    candidates: list[CandidateResultOut] = []


class AdvisorDecisionRequest(BaseModel):
    decision: str  # "accept" | "ignore"
