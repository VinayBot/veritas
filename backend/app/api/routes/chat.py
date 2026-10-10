"""POST /api/v1/chat — SSE stream of the answer, citations and report_id (Section 13 contract).

The full turn (retrieval, synthesis, verification) runs to completion before anything streams:
the Verifier can send the answer back to the Synthesizer for revision, so there is no safe way
to stream raw tokens as the first draft generates — the user would see unverified text. Once
the final, verified answer exists, it's chunked over SSE for a responsive "typing" feel. This
is real data delivered progressively, not fabricated incremental generation — see
docs/DECISIONS.md.
"""

from __future__ import annotations

import asyncio
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
    # Runs the turn as a background task rather than a plain `await`, so the "session" event
    # can be yielded the moment run_chat_turn's on_session_started fires — right after its one
    # cheap cache lookup — instead of only once the whole (potentially slow, multi-LLM-call)
    # turn finishes. This is what lets the Architecture tab subscribe to this session's trace
    # feed and show live progress for a brand-new conversation's first message, not just a
    # retroactive replay after the fact. See docs/TROUBLESHOOTING.md.
    session_ready = asyncio.Event()
    session_info: dict[str, object] = {}

    async def _on_session_started(session_id: str, cache_hit: bool) -> None:
        session_info["session_id"] = session_id
        session_info["cache_hit"] = cache_hit
        session_ready.set()

    task = asyncio.ensure_future(
        run_chat_turn(
            body.message,
            body.document_id,
            mode=body.mode,
            reveal_pii=body.reveal_pii,
            session_id=body.session_id,
            council=body.council,
            on_session_started=_on_session_started,
        )
    )

    session_waiter = asyncio.ensure_future(session_ready.wait())
    _done, pending = await asyncio.wait([task, session_waiter], return_when=asyncio.FIRST_COMPLETED)
    for leftover in pending:
        # Whichever of the two didn't win the race is done being useful — if it's
        # `session_waiter`, it would otherwise dangle forever (the event may never fire, e.g.
        # the invalid-mode ValueError case below); if it's `task`, it keeps running regardless
        # (asyncio tasks aren't cancelled by going unreferenced) and is awaited just below.
        if leftover is session_waiter:
            leftover.cancel()
    if session_ready.is_set():
        yield _sse(
            "session",
            {"session_id": session_info["session_id"], "cache_hit": session_info["cache_hit"]},
        )

    try:
        result = await task
    except ValueError as exc:
        yield _sse("error", {"code": "invalid_chat_mode", "message": str(exc)})
        return

    if not session_ready.is_set():
        # mode was invalid and run_chat_turn raised before ever calling the callback — the
        # ValueError branch above already handled that; this is just defensive completeness.
        yield _sse(
            "session", {"session_id": result["session_id"], "cache_hit": result["cache_hit"]}
        )

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
