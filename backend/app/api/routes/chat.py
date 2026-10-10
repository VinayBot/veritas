"""POST /api/v1/chat — SSE stream of the answer, citations and report_id (Section 13 contract).

The full turn (retrieval, synthesis, verification) runs to completion before anything streams:
the Verifier can send the answer back to the Synthesizer for revision, so there is no safe way
to stream raw tokens as the first draft generates — the user would see unverified text. Once
the final, verified answer exists, it's chunked over SSE for a responsive "typing" feel. This
is real data delivered progressively, not fabricated incremental generation — see
docs/DECISIONS.md.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agents.orchestrator import run_chat_turn
from app.api.schemas.chat import ChatRequest

router = APIRouter(tags=["chat"])


def _sse(event: str, data) -> str:
    payload = data if isinstance(data, str) else json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


async def _stream_chat(body: ChatRequest) -> AsyncIterator[str]:
    try:
        result = await run_chat_turn(
            body.message,
            body.document_id,
            mode=body.mode,
            reveal_pii=body.reveal_pii,
            session_id=body.session_id,
            council=body.council,
        )
    except ValueError as exc:
        yield _sse("error", {"code": "invalid_chat_mode", "message": str(exc)})
        return

    yield _sse("session", {"session_id": result["session_id"], "cache_hit": result["cache_hit"]})

    words = result["answer"].split(" ")
    buffer = ""
    for i, word in enumerate(words):
        buffer += word + (" " if i < len(words) - 1 else "")
        if len(buffer) > 20 or i == len(words) - 1:
            yield _sse("token", buffer)
            buffer = ""

    yield _sse("citations", [c for c in result["citations"]])
    yield _sse("agent_steps", [s for s in result["agent_steps"]])
    yield _sse("quality", result["quality"])
    if result["routing"]:
        yield _sse("routing", result["routing"])
    if result["council_run_id"]:
        yield _sse("council_run_id", result["council_run_id"])
    yield _sse("done", {"report_id": result["report_id"], "cache_hit": result["cache_hit"]})


@router.post("/chat")
async def chat(body: ChatRequest) -> StreamingResponse:
    return StreamingResponse(_stream_chat(body), media_type="text/event-stream")
