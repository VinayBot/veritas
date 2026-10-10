from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.schemas.profiler import (
    AdvisorDecisionRequest,
    AdvisorResponse,
    CandidateResultOut,
    ProfileResponse,
)
from app.core.errors import AppError
from app.evaluation.models import AdvisorRecommendation as AdvisorRecommendationRow
from app.ingestion import service as ingestion_service
from app.profiler import service as profiler_service
from app.profiler.features import DocumentProfile

router = APIRouter(tags=["profiler"])


def _advisor_response(document_id: str, row: AdvisorRecommendationRow) -> AdvisorResponse:
    def _candidate(config: dict[str, Any], metrics: dict[str, Any]) -> CandidateResultOut:
        return CandidateResultOut.model_validate({**config, **metrics})

    return AdvisorResponse(
        document_id=document_id,
        baseline=_candidate(row.baseline_config, row.baseline_metrics),
        suggested=_candidate(row.suggested_config, row.suggested_metrics),
        gain_ndcg_points=row.gain_ndcg,
        rationale=row.rationale,
        suggested_mode=row.suggested_mode,
        mode_reason=row.mode_reason,
        decision=row.decision,
    )


async def _profile_for(document_id: str) -> tuple[DocumentProfile, str]:
    doc = await ingestion_service.get_document(document_id)
    if doc is None:
        raise AppError("document_not_found", f"No document with id {document_id}", 404)
    if doc.masked_text is None:
        raise AppError(
            "document_not_ready", f"Document {document_id} has not finished ingestion", 422
        )
    doc_profile = await profiler_service.profile(
        document_id, doc.masked_text, doc.language, doc.ocr_confidence
    )
    return doc_profile, doc.masked_text


@router.get("/documents/{document_id}/profile", response_model=ProfileResponse)
async def get_profile(document_id: str) -> ProfileResponse:
    doc_profile, _ = await _profile_for(document_id)
    return ProfileResponse(**doc_profile.model_dump())


@router.post("/documents/{document_id}/advisor/run", response_model=AdvisorResponse)
async def run_advisor(document_id: str) -> AdvisorResponse:
    doc_profile, text = await _profile_for(document_id)
    recommendation = await profiler_service.run_advisor(document_id, text, doc_profile)
    if recommendation is None:
        raise AppError(
            "advisor_unavailable",
            "Not enough indexed content for a meaningful chunking comparison, or no "
            "synthetic eval items could be generated (LLM may be unavailable)",
            422,
        )
    row = await profiler_service.get_latest_recommendation(document_id)
    assert row is not None
    return _advisor_response(document_id, row)


@router.get("/documents/{document_id}/advisor", response_model=AdvisorResponse)
async def get_advisor(document_id: str) -> AdvisorResponse:
    row = await profiler_service.get_latest_recommendation(document_id)
    if row is None:
        raise AppError("no_recommendation", f"No advisor recommendation yet for {document_id}", 404)
    return _advisor_response(document_id, row)


@router.post("/documents/{document_id}/advisor/decision", response_model=AdvisorResponse)
async def decide_advisor(document_id: str, body: AdvisorDecisionRequest) -> AdvisorResponse:
    try:
        row = await profiler_service.record_decision(document_id, body.decision)
    except profiler_service.AdvisorError as exc:
        status_code = 404 if exc.code in {"no_recommendation", "document_not_found"} else 422
        raise AppError(exc.code, exc.message, status_code) from exc
    return _advisor_response(document_id, row)
