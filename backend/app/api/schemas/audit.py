from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AuditEntryResponse(BaseModel):
    id: int
    trace_id: str
    session_id: str
    layer: str
    rule: str
    score: float | None
    decision: str
    redacted_excerpt: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditListResponse(BaseModel):
    entries: list[AuditEntryResponse]


class AuditRuleSummary(BaseModel):
    layer: str
    rule: str
    total: int
    allow: int
    redact: int
    block: int
    escalate: int
    """Share of this rule's decisions that were anything other than "allow"."""
    trip_rate: float


class AuditSummaryResponse(BaseModel):
    """Counted over real traffic only: red-team and evaluation sessions are excluded, so a
    suite run does not inflate the block rate people see for their own questions."""

    total: int
    by_decision: dict[str, int]
    by_layer: dict[str, int]
    rules: list[AuditRuleSummary]
    trip_rate: float | None
    first_at: datetime | None
    last_at: datetime | None
