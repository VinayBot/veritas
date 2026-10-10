from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.schemas.audit import AuditEntryResponse, AuditListResponse
from app.core.db import session_scope
from app.guardrails.audit import AuditLogEntry

router = APIRouter(tags=["audit"])


@router.get("/audit", response_model=AuditListResponse)
async def list_audit(
    session_id: str | None = None, layer: str | None = None, limit: int = 100
) -> AuditListResponse:
    limit = min(limit, 500)
    async with session_scope() as session:
        query = select(AuditLogEntry).order_by(AuditLogEntry.id.desc()).limit(limit)
        if session_id:
            query = query.where(AuditLogEntry.session_id == session_id)
        if layer:
            query = query.where(AuditLogEntry.layer == layer)
        rows = (await session.execute(query)).scalars().all()
    return AuditListResponse(entries=[AuditEntryResponse.model_validate(r) for r in rows])
