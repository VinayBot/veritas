from __future__ import annotations

from pydantic import BaseModel


class SelfTestCheck(BaseModel):
    name: str
    ok: bool
    detail: str
    duration_ms: float


class SelfTestResponse(BaseModel):
    checks: list[SelfTestCheck]
    all_ok: bool
