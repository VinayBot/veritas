"""Local model selection: what is installed, what is selected for each role, whether the
selection fits the machine, and re-indexing after an embedding-model change."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.core import jobs, runtime_settings
from app.core.errors import AppError
from app.llm import models_catalog
from app.llm.models_config import get_model_config
from app.retrieval import index_guard, semantic_cache

router = APIRouter(tags=["models"])

_FIELD_TO_SETTING = {
    "generator": "generator_model",
    "judge": "judge_model",
    "council": "council_models",
    "chairman": "chairman_model",
    "embedding": "embedding_model",
    "reranker": "reranker_model",
}


class SelectionRequest(BaseModel):
    """Only the fields present are changed."""

    generator: str | None = None
    judge: str | None = None
    council: list[str] | None = None
    chairman: str | None = None
    embedding: str | None = None
    reranker: str | None = None


class ReindexRequest(BaseModel):
    """Omit `document_ids` to re-index every stale document."""

    document_ids: list[str] | None = None


class StartedJob(BaseModel):
    job_id: str


async def _state() -> dict:
    return {**await models_catalog.catalog(), "index": await index_guard.index_status()}


@router.get("/models/local")
async def local_models() -> dict:
    """Installed models and the current selection. If Ollama is not running, `ollama.status`
    is "down" with the exact error and the command that starts it."""
    return await _state()


@router.put("/models/selection")
async def set_selection(body: SelectionRequest) -> dict:
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise AppError("invalid_model_selection", "No model was given to change.", 422)
    try:
        await models_catalog.validate_selection(changes)
    except models_catalog.SelectionError as exc:
        raise AppError("invalid_model_selection", exc.message, 422) from exc

    previous_embedding = get_model_config().embedding
    for field, value in changes.items():
        await runtime_settings.set_value(_FIELD_TO_SETTING[field], value)
    if get_model_config().embedding != previous_embedding:
        # Cached question vectors came from the old model and can no longer be compared.
        semantic_cache.clear()
    return await _state()


@router.post("/models/reset")
async def reset_selection() -> dict:
    """Clears every stored choice, returning to the `.env` defaults."""
    previous_embedding = get_model_config().embedding
    for setting in _FIELD_TO_SETTING.values():
        await runtime_settings.set_value(setting, None)
    if get_model_config().embedding != previous_embedding:
        semantic_cache.clear()
    return await _state()


@router.get("/models/index-status")
async def index_status() -> dict:
    return await index_guard.index_status()


@router.post("/models/reindex", response_model=StartedJob)
async def reindex(body: ReindexRequest) -> StartedJob:
    """Re-embeds stale documents with the active embedding model, as a background job."""
    job = await jobs.create_job("reindex", body.model_dump())

    async def work(ctx: jobs.JobContext) -> dict:
        return await index_guard.reindex_stale(body.document_ids, ctx.progress)

    jobs.launch(job.id, work)
    return StartedJob(job_id=job.id)
