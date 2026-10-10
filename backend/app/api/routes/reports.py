from __future__ import annotations

from fastapi import APIRouter

from app.agents.models import ChatReport
from app.api.schemas.chat import ReportResponse
from app.core.db import session_scope
from app.core.errors import AppError

router = APIRouter(tags=["reports"])


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report(report_id: str) -> ReportResponse:
    async with session_scope() as session:
        report = await session.get(ChatReport, report_id)
    if report is None:
        raise AppError("report_not_found", f"No report with id {report_id}", 404)
    return ReportResponse.model_validate(report, from_attributes=True)
