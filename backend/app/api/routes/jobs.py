"""Background jobs: status, a resumable progress stream, and cancellation."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core import jobs
from app.core.errors import AppError

router = APIRouter(tags=["jobs"])


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    params: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    progress: float
    message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobListOut(BaseModel):
    jobs: list[JobOut]


@router.get("/jobs", response_model=JobListOut)
async def list_jobs(kind: str | None = None, active: bool = False, limit: int = 20) -> JobListOut:
    rows = await jobs.list_jobs(kind=kind, active_only=active, limit=max(1, min(limit, 100)))
    return JobListOut(jobs=[JobOut.model_validate(r) for r in rows])


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: str) -> JobOut:
    job = await jobs.get_job(job_id)
    if job is None:
        raise AppError("job_not_found", f"No job with id {job_id}", 404)
    return JobOut.model_validate(job)


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    try:
        return {"status": await jobs.cancel(job_id)}
    except KeyError as exc:
        raise AppError("job_not_found", f"No job with id {job_id}", 404) from exc


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str, after_seq: int = Query(default=-1)) -> StreamingResponse:
    if await jobs.get_job(job_id) is None:
        raise AppError("job_not_found", f"No job with id {job_id}", 404)

    async def generate() -> AsyncIterator[str]:
        async for event in jobs.stream(job_id, after_seq=after_seq):
            payload = json.dumps(
                {
                    "seq": event.seq,
                    **(event.data if isinstance(event.data, dict) else {"value": event.data}),
                }
            )
            yield f"id: {event.seq}\nevent: {event.event}\ndata: {payload}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
