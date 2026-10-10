"""Explicit, audited de-tokenization. Every call here is written to the PII reveal audit
trail (app/privacy/models.py: PiiRevealEvent) — there is no silent reveal path.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.pii import PiiRevealRequest, PiiRevealResponse
from app.privacy import vault

router = APIRouter(tags=["pii"])


@router.post("/pii/reveal", response_model=PiiRevealResponse)
async def reveal_pii(body: PiiRevealRequest) -> PiiRevealResponse:
    revealed = await vault.reveal_many(body.tokens, body.session_id)
    not_found = [t for t in body.tokens if t not in revealed]
    return PiiRevealResponse(revealed=revealed, not_found=not_found)
