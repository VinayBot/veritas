"""Not in the original Section 13 contract — added now so Phase 3's hybrid search is actually
exercisable end to end (not just unit-tested), and because Phase 6's agentic `hybrid_search`
tool is this exact call. Documented in docs/API.md."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.retrieval import SearchHit, SearchRequest, SearchResponse
from app.core.errors import AppError
from app.retrieval import service

router = APIRouter(tags=["retrieval"])


@router.post("/retrieval/search", response_model=SearchResponse)
async def search(body: SearchRequest) -> SearchResponse:
    try:
        hits = await service.search(
            body.query,
            k=body.k,
            doc_id=body.document_id,
            mode=body.mode,
            use_hyde=body.use_hyde,
            rerank=body.rerank,
            dedupe_strategy=body.dedupe_strategy,
            compress=body.compress,
            max_context_tokens=body.max_context_tokens,
        )
    except ValueError as exc:
        raise AppError("invalid_search_request", str(exc), 422) from exc
    return SearchResponse(hits=[SearchHit(**h.model_dump()) for h in hits])
