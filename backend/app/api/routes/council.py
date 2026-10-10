from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.council import CouncilRunResponse
from app.core.errors import AppError
from app.council.service import get_council_run

router = APIRouter(tags=["council"])


@router.get("/council/{run_id}", response_model=CouncilRunResponse)
async def get_council(run_id: str) -> CouncilRunResponse:
    run = await get_council_run(run_id)
    if run is None:
        raise AppError("council_run_not_found", f"No council run with id {run_id}", 404)
    return CouncilRunResponse.model_validate(run, from_attributes=True)
