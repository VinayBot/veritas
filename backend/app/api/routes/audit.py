from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.schemas.audit import (
    AuditEntryResponse,
    AuditListResponse,
    AuditRuleSummary,
    AuditSummaryResponse,
)
from app.core.db import session_scope
from app.guardrails.audit import AuditLogEntry

router = APIRouter(tags=["audit"])

# Session-id prefixes used by synthetic runs (app/guardrails/redteam/runner.py and the
# evaluation harness) — not questions a person asked.
SYNTHETIC_SESSION_PREFIXES = ("redteam-", "eval-", "selfcheck-")


def _real_traffic() -> list:
    return [AuditLogEntry.session_id.not_like(f"{p}%") for p in SYNTHETIC_SESSION_PREFIXES]


@router.get("/audit/summary", response_model=AuditSummaryResponse)
async def audit_summary() -> AuditSummaryResponse:
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(
                    AuditLogEntry.layer,
                    AuditLogEntry.rule,
                    AuditLogEntry.decision,
                    func.count(),
                )
                .where(*_real_traffic())
                .group_by(AuditLogEntry.layer, AuditLogEntry.rule, AuditLogEntry.decision)
            )
        ).all()
        first_at, last_at = (
            await session.execute(
                select(
                    func.min(AuditLogEntry.created_at), func.max(AuditLogEntry.created_at)
                ).where(*_real_traffic())
            )
        ).one()

    by_decision: dict[str, int] = {}
    by_layer: dict[str, int] = {}
    per_rule: dict[tuple[str, str], dict[str, int]] = {}
    for layer, rule, decision, count in rows:
        by_decision[decision] = by_decision.get(decision, 0) + count
        by_layer[layer] = by_layer.get(layer, 0) + count
        per_rule.setdefault((layer, rule), {})[decision] = count

    rules = []
    for (layer, rule), counts in per_rule.items():
        total = sum(counts.values())
        allow = counts.get("allow", 0)
        rules.append(
            AuditRuleSummary(
                layer=layer,
                rule=rule,
                total=total,
                allow=allow,
                redact=counts.get("redact", 0),
                block=counts.get("block", 0),
                escalate=counts.get("escalate", 0),
                trip_rate=(total - allow) / total if total else 0.0,
            )
        )
    rules.sort(key=lambda r: (r.total - r.allow, r.total), reverse=True)

    total = sum(by_decision.values())
    return AuditSummaryResponse(
        total=total,
        by_decision=by_decision,
        by_layer=by_layer,
        rules=rules,
        trip_rate=(total - by_decision.get("allow", 0)) / total if total else None,
        first_at=first_at,
        last_at=last_at,
    )


@router.get("/audit", response_model=AuditListResponse)
async def list_audit(
    session_id: str | None = None,
    layer: str | None = None,
    decision: str | None = None,
    real_traffic_only: bool = False,
    limit: int = 100,
) -> AuditListResponse:
    limit = min(limit, 500)
    async with session_scope() as session:
        query = select(AuditLogEntry).order_by(AuditLogEntry.id.desc()).limit(limit)
        if session_id:
            query = query.where(AuditLogEntry.session_id == session_id)
        if layer:
            query = query.where(AuditLogEntry.layer == layer)
        if decision:
            query = query.where(AuditLogEntry.decision == decision)
        if real_traffic_only:
            query = query.where(*_real_traffic())
        rows = (await session.execute(query)).scalars().all()
    return AuditListResponse(entries=[AuditEntryResponse.model_validate(r) for r in rows])
