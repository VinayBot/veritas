from __future__ import annotations

from pydantic import BaseModel


class PiiRevealRequest(BaseModel):
    tokens: list[str]
    session_id: str


class PiiRevealResponse(BaseModel):
    revealed: dict[str, str]
    not_found: list[str]
