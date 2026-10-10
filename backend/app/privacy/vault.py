"""The encrypted vault: token -> original value. The only place raw PII is ever persisted."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.core.db import session_scope
from app.privacy.models import PiiRevealEvent, PiiVaultEntry


class VaultKeyMissingError(Exception):
    pass


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    settings = get_settings()
    if not settings.pii_vault_key:
        raise VaultKeyMissingError(
            "PII_VAULT_KEY is not set. Generate one with: "
            'uv run python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    return Fernet(settings.pii_vault_key.encode())


async def store(token: str, entity_type: str, value: str, document_id: str | None = None) -> None:
    """Idempotent: storing the same token again is a no-op (deterministic tokens repeat)."""
    fernet = _get_fernet()
    async with session_scope() as session:
        existing = await session.get(PiiVaultEntry, token)
        if existing is not None:
            return
        entry = PiiVaultEntry(
            token=token,
            entity_type=entity_type,
            ciphertext=fernet.encrypt(value.encode()),
            document_id=document_id,
            created_at=datetime.now(UTC),
        )
        session.add(entry)
        await session.commit()


async def reveal(token: str, session_id: str) -> str | None:
    """Decrypts and returns the original value, logging the reveal to the audit trail."""
    fernet = _get_fernet()
    async with session_scope() as session:
        entry = await session.get(PiiVaultEntry, token)
        if entry is None:
            return None
        value = fernet.decrypt(entry.ciphertext).decode()
        session.add(
            PiiRevealEvent(token=token, session_id=session_id, revealed_at=datetime.now(UTC))
        )
        await session.commit()
        return value


async def reveal_many(tokens: list[str], session_id: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in tokens:
        value = await reveal(token, session_id)
        if value is not None:
            out[token] = value
    return out


async def exists(token: str) -> bool:
    """Direct reverse lookup: the caller already computed `token` from a known value (e.g. an
    email typed into a chat query via tokenizer.make_token) and wants to know whether it's in
    the vault at all before trying to reveal it. The real `pii_vault_lookup` agent tool (Phase 6)
    is built on this plus tokenizer.make_token — looking up PII by a *fragment* of an opaque,
    HMAC-derived token would be meaningless, so that's intentionally not offered here."""
    async with session_scope() as session:
        return await session.get(PiiVaultEntry, token) is not None
