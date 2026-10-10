from __future__ import annotations

from pydantic import BaseModel


class RedTeamCategoryResult(BaseModel):
    total: int
    blocked: int
    block_rate: float


class RedTeamRunResponse(BaseModel):
    total_attacks: int
    blocked_attacks: int
    block_rate: float
    total_benign: int
    false_positives: int
    false_positive_rate: float
    by_category: dict[str, RedTeamCategoryResult]
