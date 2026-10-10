from __future__ import annotations

from pydantic import BaseModel


class ProfileResponse(BaseModel):
    document_id: str
    pages_estimated: int
    tokens: int
    language: str | None
    heading_density: float
    table_ratio: float
    list_ratio: float
    code_ratio: float
    avg_sentence_length: float
    avg_paragraph_length: float
    duplication_ratio: float
    ocr_confidence: float | None
    entity_density: float
    relation_density: float
    document_type: str


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


class AdvisorResponse(BaseModel):
    document_id: str
    baseline: CandidateResultOut
    suggested: CandidateResultOut
    gain_ndcg_points: float
    rationale: list[str]
    suggested_mode: str
    mode_reason: str
    decision: str | None


class AdvisorDecisionRequest(BaseModel):
    decision: str  # "accept" | "ignore"
