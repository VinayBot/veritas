"""Deterministic PII tokenization: the same (type, value) always yields the same token, so the
same person's email matches across documents and in later queries — but the token reveals
nothing about the value (HMAC-SHA256, not a reversible hash).
"""

from __future__ import annotations

import hashlib
import hmac

from app.core.config import get_settings


def _normalize(value: str) -> str:
    return " ".join(value.strip().lower().split())


def token_id(entity_type: str, value: str) -> str:
    settings = get_settings()
    payload = f"{entity_type}:{_normalize(value)}".encode()
    digest = hmac.new(settings.pii_hmac_secret.encode(), payload, hashlib.sha256).hexdigest()
    return digest[:6]


def make_token(entity_type: str, value: str) -> str:
    return f"<{entity_type}_{token_id(entity_type, value)}>"


def mask_preview(entity_type: str, value: str) -> str:
    """A human-readable masked form (j***@acme.com) for display when PII isn't revealed."""
    if entity_type == "EMAIL_ADDRESS" and "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}***@{domain}"
    if len(value) <= 4:
        return "*" * len(value)
    return value[0] + "*" * (len(value) - 2) + value[-1]
