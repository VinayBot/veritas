"""WS /ws/trace/{session_id} — the Architecture tab's only source of animation. A client that
connects mid-pipeline gets the full history replayed first (so a late subscriber still sees
every stage that already ran), then every new TraceEvent as trace_bus publishes it. Nothing
here is synthesized: this is a thin pass-through onto app/core/tracing.py's real event bus.
"""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.tracing import trace_bus

router = APIRouter()


@router.websocket("/ws/trace/{session_id}")
async def trace_feed(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    queue = trace_bus.subscribe(session_id)
    try:
        for event in trace_bus.history(session_id):
            await websocket.send_text(event.model_dump_json())
        while True:
            event = await queue.get()
            await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        trace_bus.unsubscribe(session_id, queue)
