from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    document_id: str | None = None
    mode: str = "agentic"  # "agentic" | "hybrid" | "graph"
    council: bool = False  # opt-in multi-model council synthesis — see app/council/service.py
    reveal_pii: bool = False
    session_id: str | None = None


class ChatCitation(BaseModel):
    marker: int
    chunk_id: str
    text: str


class AgentStep(BaseModel):
    node: str
    summary: str


class QualityReport(BaseModel):
    label: str  # "estimated" (reference-free) — live chat has no ground truth to verify against
    faithfulness: float | None  # None when there were no citations to be faithful to
    relevancy: float
    citation_validity: float
    confidence: float


class RoutingInfo(BaseModel):
    primary_model: str
    model_used: str
    fell_back: bool
    latency_ms: float


class ChatTurnResult(BaseModel):
    session_id: str
    answer: str
    citations: list[ChatCitation]
    agent_steps: list[AgentStep]
    report_id: str
    cache_hit: bool
    quality: QualityReport
    council_run_id: str | None = None
    routing: RoutingInfo | None = None


class ReportResponse(BaseModel):
    id: str
    session_id: str
    document_id: str | None
    mode: str
    query: str
    answer: str
    citations: list[ChatCitation]
    agent_steps: list[AgentStep]
    cache_hit: bool
    quality: QualityReport
    council_run_id: str | None = None
    routing: RoutingInfo | None = None
