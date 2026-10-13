from __future__ import annotations

from fastapi import APIRouter

from app.agents.models import ChatReport
from app.api.schemas.chat import ReportResponse
from app.core.db import session_scope
from app.core.errors import AppError
from app.rag_engines.registry import strategy_for_report

router = APIRouter(tags=["reports"])


def report_response(report: ChatReport) -> ReportResponse:
    return ReportResponse.model_validate(
        dict(
            id=report.id,
            session_id=report.session_id,
            document_id=report.document_id,
            strategy=strategy_for_report(report.strategy, report.mode),
            detail=report.detail,
            outcome=report.outcome,
            query=report.query,
            answer=report.answer,
            citations=report.citations,
            agent_steps=report.agent_steps,
            cache_hit=report.cache_hit,
            quality=report.quality,
            council_run_id=report.council_run_id,
            routing=report.routing,
            latency_ms=report.latency_ms,
            usage=report.usage,
            retrieval=report.retrieval,
            timings=report.timings,
            loops=report.loops,
            created_at=report.created_at.isoformat(),
        )
    )


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report(report_id: str) -> ReportResponse:
    async with session_scope() as session:
        report = await session.get(ChatReport, report_id)
    if report is None:
        raise AppError("report_not_found", f"No report with id {report_id}", 404)
    return report_response(report)
