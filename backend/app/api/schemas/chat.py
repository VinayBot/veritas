from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    document_id: str | None = None
    """A RAG strategy id from GET /rag/strategies. Omitted = the workspace default."""
    strategy: str | None = None
    """"brief" (3-4 lines) or "deep" (7-8 lines). Omitted = decided from how the question is
    phrased: asking for detail gets the deep answer."""
    detail: str | None = None
    reveal_pii: bool = False
    session_id: str | None = None


class ChatCitation(BaseModel):
    marker: int
    chunk_id: str
    text: str


class AgentStep(BaseModel):
    node: str
    summary: str


class GroundedSentence(BaseModel):
    text: str
    supported: bool


class GroundingReport(BaseModel):
    """Supported sentences / checked sentences, with each sentence's verdict."""

    score: float
    sentences: list[GroundedSentence]
    supported: int
    total: int


class QualityReport(BaseModel):
    label: str  # "estimated" (reference-free) — live chat has no ground truth to verify against
    """Every score is None when it could not be measured; nothing is filled in."""
    faithfulness: float | None = None
    relevancy: float | None = None
    citation_validity: float | None = None
    grounding: GroundingReport | None = None
    confidence: float | None = None
    judge_model: str | None = None
    not_measured_reason: str | None = None


class RoutingInfo(BaseModel):
    primary_model: str
    model_used: str
    fell_back: bool
    latency_ms: float


class RetrievedChunk(BaseModel):
    position: int
    chunk_id: str
    text: str
    score: float | None = None
    source: str | None = None
    """Why it is in the context: "dense" | "sparse" | "both" | "graph" (or "both+graph")."""
    found_by: str | None = None
    dense_rank: int | None = None
    sparse_rank: int | None = None
    rerank_score: float | None = None
    section_path: str | None = None
    """None for every document today: no parser records page numbers yet."""
    page: int | None = None
    chunking: str | None = None
    used: bool = False
    citation_marker: int | None = None
    flagged_injection: bool = False


class RetrievalFunnel(BaseModel):
    searches: int
    dense_candidates: int | None = None
    sparse_candidates: int | None = None
    after_fusion: int | None = None
    after_rerank: int | None = None
    returned: int | None = None
    in_context: int
    used_in_answer: int


class RetrievalRecord(BaseModel):
    funnel: RetrievalFunnel | None = None
    chunks: list[RetrievedChunk] = []


class StageTiming(BaseModel):
    stage: str
    status: str
    started_at: str
    duration_ms: float | None = None
    input_preview: str | None = None
    output_preview: str | None = None
    metrics: dict[str, Any] = {}


class ReportResponse(BaseModel):
    id: str
    session_id: str
    document_id: str | None
    strategy: str
    detail: str | None = None
    outcome: str | None = None
    query: str
    answer: str
    citations: list[ChatCitation]
    agent_steps: list[AgentStep]
    cache_hit: bool
    quality: QualityReport
    council_run_id: str | None = None
    routing: RoutingInfo | None = None
    latency_ms: float | None = None
    """{llm_calls, prompt_tokens, completion_tokens, by_model, models}. None on reports
    written before token accounting existed."""
    usage: dict[str, Any] | None = None
    retrieval: RetrievalRecord | None = None
    timings: list[StageTiming] | None = None
    loops: dict[str, Any] | None = None
    created_at: str
