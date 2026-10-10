from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.redteam import RedTeamCategoryResult, RedTeamRunResponse
from app.guardrails.redteam.runner import run_redteam_suite

router = APIRouter(tags=["redteam"])


@router.post("/redteam/run", response_model=RedTeamRunResponse)
async def run_redteam() -> RedTeamRunResponse:
    report = await run_redteam_suite()
    return RedTeamRunResponse(
        total_attacks=report.total_attacks,
        blocked_attacks=report.blocked_attacks,
        block_rate=report.block_rate,
        total_benign=report.total_benign,
        false_positives=report.false_positives,
        false_positive_rate=report.false_positive_rate,
        by_category={
            category: RedTeamCategoryResult(
                total=stats.total, blocked=stats.blocked, block_rate=stats.block_rate
            )
            for category, stats in report.by_category().items()
        },
    )
