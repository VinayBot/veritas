"""GET /api/v1/health — liveness plus a real (not assumed) check of the Ollama backend and the
startup preflight's live status (see app/core/preflight.py)."""

from __future__ import annotations

import httpx
from fastapi import APIRouter

from app.core.config import get_settings
from app.core.preflight import get_last_report

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    ollama_status = "unreachable"
    local_models: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            payload = resp.json()
            local_models = [m["name"] for m in payload.get("models", [])]
            ollama_status = "up"
    except (httpx.HTTPError, KeyError, ValueError):
        ollama_status = "unreachable"

    report = get_last_report()
    if report is None:
        preflight: dict = {"status": "running", "checks": []}
    else:
        preflight = {"status": "ok" if report.all_ok else "degraded", **report.to_dict()}

    return {
        "status": "ok",
        "app_env": settings.app_env,
        "hardware_tier": settings.hardware_tier,
        "ollama": {"status": ollama_status, "models": local_models},
        "vector_store": settings.vector_store,
        "graph_store": settings.graph_store,
        "preflight": preflight,
    }
