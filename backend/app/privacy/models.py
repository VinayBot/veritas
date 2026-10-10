"""The PII vault: encrypted token -> original value, plus a reveal audit trail.

Raw PII is only ever written here (Fernet-encrypted). Every other store (vector index, BM25,
graph, prompts, logs, traces) only ever sees the deterministic token.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PiiVaultEntry(Base):
    __tablename__ = "pii_vault_entries"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class PiiRevealEvent(Base):
    __tablename__ = "pii_reveal_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(String(64))
    session_id: Mapped[str] = mapped_column(String(64))
    revealed_at: Mapped[datetime] = mapped_column(DateTime)
