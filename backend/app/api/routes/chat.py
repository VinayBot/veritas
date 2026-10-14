"""POST /api/v1/chat — creates a persisted ChatRun and streams its events over SSE.

Fix 1 (see docs/DECISIONS.md): previously this endpoint's SSE generator just launched the turn
and `await`ed it directly with no persisted state and no intermediate output — a client that
disconnected, or a turn that took a long time, had no way to find out what was happening or to
reattach. Now: `POST /chat` creates a `ChatRun` row and starts `run_chat_turn_tracked` (which
owns the overall timeout, retry, and budget — see app/agents/orchestrator.py) as a background
task that outlives this request, then streams whatever `runs.stream_run` reads back from the
durable event log. `GET /api/v1/runs/{run_id}/stream` (app/api/routes/runs.py) serves the exact
same event log for a client reattaching after a drop, via `after_seq`.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agents import runs
from app.agents.answer_style import DETAIL_LEVELS, resolve_detail
from app.agents.orchestrator import cache_scope, run_chat_turn_tracked
from app.api.schemas.chat import ChatRequest
from app.guardrails.rate_limit import limit_client
from app.rag_engines.document_strategy import effective_strategy
from app.rag_engines.registry import UnknownStrategyError, get_strategy
from app.retrieval import semantic_cache

router = APIRouter(tags=["chat"])


def _sse(event: str, data) -> str:
    # Always JSON, including plain strings: an answer can contain a blank line, and a raw
    # blank line inside `data:` would end the SSE frame early and drop the rest of the text.
    payload = json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


async def _stream_new_run(
    run_id: str, session_id: str, cache_hit: bool, strategy: str, detail: str
) -> AsyncIterator[str]:
    yield _sse(
        "session",
        {
            "run_id": run_id,
            "session_id": session_id,
            "cache_hit": cache_hit,
            "strategy": strategy,
            "detail": detail,
        },
    )
    async for ev in runs.stream_run(run_id, after_seq=-1):
        yield _sse(ev.event, ev.data)


@router.post("/chat", dependencies=[Depends(limit_client("chat"))])
async def chat(body: ChatRequest) -> StreamingResponse:
    strategy_id = body.strategy or (await effective_strategy(body.document_id))[0]
    try:
        get_strategy(strategy_id)
    except UnknownStrategyError as exc:
        return StreamingResponse(
            iter([_sse("error", {"code": "invalid_strategy", "message": str(exc)})]),
            media_type="text/event-stream",
        )
    if body.detail is not None and body.detail not in DETAIL_LEVELS:
        return StreamingResponse(
            iter(
                [
                    _sse(
                        "error",
                        {
                            "code": "invalid_detail",
                            "message": f"detail must be one of {DETAIL_LEVELS} or omitted",
                        },
                    )
                ]
            ),
            media_type="text/event-stream",
        )

    run_id = str(uuid.uuid4())
    session_id = body.session_id or str(uuid.uuid4())
    detail = resolve_detail(body.message, body.detail)
    # Looked up here (cheap: one embedding + a linear scan) purely so the "session" event can
    # report cache_hit immediately; the background task repeats the lookup when it runs.
    cached = await semantic_cache.lookup(
        body.message, body.document_id, cache_scope(strategy_id, detail)
    )
    await runs.create_run(run_id, session_id, body.document_id, strategy_id, body.message)
    runs.launch_run(
        run_id,
        run_chat_turn_tracked(
            run_id,
            body.message,
            body.document_id,
            strategy_id,
            body.reveal_pii,
            session_id,
            body.detail,
        ),
    )
    return StreamingResponse(
        _stream_new_run(
            run_id, session_id, cache_hit=cached is not None, strategy=strategy_id, detail=detail
        ),
        media_type="text/event-stream",
    )
