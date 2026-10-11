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

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agents import runs
from app.agents.orchestrator import VALID_MODES, run_chat_turn_tracked
from app.api.schemas.chat import ChatRequest
from app.retrieval import semantic_cache

router = APIRouter(tags=["chat"])


def _sse(event: str, data) -> str:
    # Deliberately the exact same wire format as before this fix (no SSE `id:` line yet) — the
    # frontend's hand-rolled fetch+ReadableStream parser (frontend/src/lib/api/client.ts) was
    # written against this shape, and changing it here without updating that parser in the same
    # commit would break every live chat turn, not just the resume case this is building toward.
    # Resume (app/api/routes/runs.py) tracks `seq` via its own JSON `data` payload instead of an
    # SSE `id:` line — see docs/DECISIONS.md.
    payload = data if isinstance(data, str) else json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


async def _stream_new_run(run_id: str, session_id: str, cache_hit: bool) -> AsyncIterator[str]:
    yield _sse("session", {"run_id": run_id, "session_id": session_id, "cache_hit": cache_hit})
    async for ev in runs.stream_run(run_id, after_seq=-1):
        yield _sse(ev.event, ev.data)


@router.post("/chat")
async def chat(body: ChatRequest) -> StreamingResponse:
    if body.mode not in VALID_MODES:
        return StreamingResponse(
            iter(
                [
                    _sse(
                        "error",
                        {
                            "code": "invalid_chat_mode",
                            "message": f"Unknown chat mode: {body.mode!r}. Valid: {VALID_MODES}",
                        },
                    )
                ]
            ),
            media_type="text/event-stream",
        )

    run_id = str(uuid.uuid4())
    session_id = body.session_id or str(uuid.uuid4())
    # Looked up here (cheap: one embedding + a linear scan — see app/retrieval/semantic_cache.py)
    # purely so the "session" event can report cache_hit immediately, matching what every
    # existing caller (including the frontend) already expects to see right away rather than
    # only once the full turn completes. run_chat_turn_tracked repeats this same lookup itself
    # when the background task actually runs — a small, deliberate redundant read rather than
    # threading a pre-fetched cache object through the tracked-run wrapper's signature.
    cached = await semantic_cache.lookup(body.message, body.document_id, body.mode)
    await runs.create_run(run_id, session_id, body.document_id, body.mode, body.message)
    runs.launch_run(
        run_id,
        run_chat_turn_tracked(
            run_id,
            body.message,
            body.document_id,
            body.mode,
            body.reveal_pii,
            session_id,
            body.council,
        ),
    )
    return StreamingResponse(
        _stream_new_run(run_id, session_id, cache_hit=cached is not None),
        media_type="text/event-stream",
    )
