"""The guardrail decision audit log: every input/retrieval/output guardrail decision is written
here (Section 10), regardless of the outcome — allow decisions are logged too, not just blocks,
since "what did the guardrails see and let through" matters as much as what they stopped.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, session_scope

Decision = str  # "allow" | "redact" | "block" | "escalate"


class AuditLogEntry(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(64))
    layer: Mapped[str] = mapped_column(String(16))  # "input" | "retrieval" | "output"
    rule: Mapped[str] = mapped_column(String(64))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str] = mapped_column(String(16))
    redacted_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


async def record(
    trace_id: str,
    session_id: str,
    layer: str,
    rule: str,
    decision: Decision,
    score: float | None = None,
    excerpt: str | None = None,
) -> None:
    async with session_scope() as session:
        session.add(
            AuditLogEntry(
                trace_id=trace_id,
                session_id=session_id,
                layer=layer,
                rule=rule,
                score=score,
                decision=decision,
                redacted_excerpt=excerpt[:500] if excerpt else None,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
