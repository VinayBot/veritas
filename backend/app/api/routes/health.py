"""Health endpoints.

- GET  /api/v1/health             liveness, Ollama reachability and the startup preflight
- GET  /api/v1/health/subsystems  one real probe per subsystem (app/core/health.py)
- POST /api/v1/health/self-check  an end-to-end pass with per-stage timings
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.core import health as health_probes
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


class SubsystemOut(BaseModel):
    id: str
    label: str
    status: str
    detail: str
    kind: str
    raw: dict[str, Any]
    error: str | None
    fix: str | None
    latency_ms: float
    p50_latency_ms: float | None
    checked_at: str


class SubsystemsResponse(BaseModel):
    checked_at: str
    subsystems: list[SubsystemOut]


@router.get("/health/subsystems", response_model=SubsystemsResponse)
async def subsystems(force: bool = False) -> SubsystemsResponse:
    results = await health_probes.run_probes(force=force)
    return SubsystemsResponse(
        checked_at=datetime.now(UTC).isoformat(),
        subsystems=[SubsystemOut(**r.to_dict()) for r in results],
    )


class SelfCheckStageOut(BaseModel):
    name: str
    label: str
    ok: bool
    duration_ms: float
    detail: str
    error: str | None


class SelfCheckResponse(BaseModel):
    ok: bool
    total_ms: float
    ran_at: str
    stages: list[SelfCheckStageOut]


@router.post("/health/self-check", response_model=SelfCheckResponse)
async def self_check() -> SelfCheckResponse:
    stages = await health_probes.run_self_check()
    health_probes.reset_cache()
    return SelfCheckResponse(
        ok=all(s.ok for s in stages),
        total_ms=round(sum(s.duration_ms for s in stages), 1),
        ran_at=datetime.now(UTC).isoformat(),
        stages=[
            SelfCheckStageOut(
                name=s.name,
                label=s.label,
                ok=s.ok,
                duration_ms=round(s.duration_ms, 1),
                detail=s.detail,
                error=s.error,
            )
            for s in stages
        ],
    )
