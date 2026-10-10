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
