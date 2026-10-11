"""GET /api/v1/runs/{run_id} and .../stream — the resume half of Fix 1 (see
docs/DECISIONS.md). A chat turn is now a persisted ChatRun (app/agents/runs.py) that keeps
going as a background task independent of the HTTP connection that started it; these two
endpoints let a client that dropped the original stream (a tab switch, a reload, a flaky
connection) find out what happened without ever having to re-ask the question.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.agents import runs

router = APIRouter(tags=["chat"])


def _sse(event: str, data, event_id: int | None = None) -> str:
    payload = data if isinstance(data, str) else json.dumps(data)
    id_line = f"id: {event_id}\n" if event_id is not None else ""
    return f"{id_line}event: {event}\ndata: {payload}\n\n"


@router.get("/runs/{run_id}")
async def get_run_status(run_id: str) -> dict:
    run = await runs.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    return {
        "id": run.id,
        "session_id": run.session_id,
        "document_id": run.document_id,
        "mode": run.mode,
        "query": run.query,
        "status": run.status,
        "stage": run.stage,
        "error": run.error,
        "report_id": run.report_id,
        "attempt": run.attempt,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str) -> dict:
    run = await runs.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    task = runs.get_in_flight_task(run_id)
    if task is not None and not task.done():
        task.cancel()
        return {"status": "cancelling"}
    return {"status": run.status}


@router.get("/runs/{run_id}/stream")
async def stream_run_resume(
    run_id: str,
    after_seq: int = Query(default=-1),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    """`after_seq` is what this project's hand-rolled fetch+ReadableStream SSE client actually
    sends (see frontend/src/lib/api/client.ts) — plain EventSource's automatic `Last-Event-ID`
    header is also honored, so this stays spec-correct if that's ever used instead."""
    run = await runs.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")

    resume_from = after_seq
    if last_event_id is not None:
        try:
            resume_from = int(last_event_id)
        except ValueError:
            pass

    async def _generate() -> AsyncIterator[str]:
        async for ev in runs.stream_run(run_id, after_seq=resume_from):
            yield _sse(ev.event, ev.data, ev.seq)

    return StreamingResponse(_generate(), media_type="text/event-stream")
