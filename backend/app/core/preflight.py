"""Startup preflight: proactively loads every heavy, lazily-initialized model once at server
boot instead of letting the first real user's upload pay that cost (and, on a cold machine,
pay it with zero progress feedback and no timeout — see docs/TROUBLESHOOTING.md for the
incident this exists to prevent). Results are cached and surfaced through GET /api/v1/health
so the frontend can show a banner if anything is actually missing/unreachable, rather than the
user discovering it mid-upload.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# backend/app/core/preflight.py -> backend/app/core -> backend/app -> backend -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_WARMUP_PDF = _REPO_ROOT / "data" / "demo" / "northwind_remote_work_travel_policy.pdf"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    duration_ms: float


@dataclass
class PreflightReport:
    checks: list[CheckResult]
    ran_at: float

    @property
    def all_ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def to_dict(self) -> dict:
        return {
            "ok": self.all_ok,
            "checks": [
                {
                    "name": c.name,
                    "ok": c.ok,
                    "detail": c.detail,
                    "duration_ms": round(c.duration_ms, 1),
                }
                for c in self.checks
            ],
        }


_last_report: PreflightReport | None = None


def get_last_report() -> PreflightReport | None:
    return _last_report


async def timed_check(name: str, fn) -> CheckResult:
    start = time.perf_counter()
    try:
        detail = await asyncio.to_thread(fn) if not asyncio.iscoroutinefunction(fn) else await fn()
        return CheckResult(name, True, detail or "ok", (time.perf_counter() - start) * 1000)
    except Exception as exc:  # noqa: BLE001 — a preflight check failing must never crash boot
        logger.warning("Preflight check %r failed: %s", name, exc, exc_info=exc)
        return CheckResult(name, False, str(exc)[:500], (time.perf_counter() - start) * 1000)


def warm_embedder() -> str:
    from app.embeddings.registry import get_embedder

    embedder = get_embedder()
    return f"{embedder.model_name} ({embedder.dimension}d)"


def _warm_pii_detector() -> str:
    from app.privacy.detector import detect

    found = detect("Call Jane Doe at jane@example.com for the warm-up check.")
    return f"presidio+spacy loaded ({len(found)} test entities found)"


def _warm_docling() -> str:
    from app.ingestion.registry import get_parser

    if not _WARMUP_PDF.exists():
        return f"skipped — warmup fixture not found at {_WARMUP_PDF}"
    parser = get_parser(".pdf")
    result = parser.parse(_WARMUP_PDF)
    return f"docling ready ({len(result.text)} chars from warmup fixture)"


def _warm_reranker() -> str:
    from app.retrieval.reranker import get_reranker

    reranker = get_reranker()
    return f"{reranker.model_name} loaded"


async def check_ollama() -> str:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{settings.ollama_base_url}/api/tags")
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
    if not models:
        raise RuntimeError("Ollama is reachable but has no models pulled")
    return f"reachable, {len(models)} model(s): {', '.join(models)}"


async def warm_ollama_models() -> str:
    """Fix 1 (see docs/DECISIONS.md): `check_ollama` above only lists installed models via
    `/api/tags` — it never calls `/api/generate`/`/api/chat`, so it never actually loads a
    model's weights into memory, unlike the embedder/reranker, which genuinely do get warmed at
    startup. The first *real* chat turn therefore pays Ollama's full cold-load latency with zero
    progress feedback. This makes one tiny real generate call per distinct configured model with
    `keep_alive` set, so weights are already resident by the time a user's first question
    arrives, and stay resident for `OLLAMA_KEEP_ALIVE` afterward.
    """
    settings = get_settings()
    if settings.llm_provider != "ollama":
        return "skipped — LLM_PROVIDER is not ollama"

    configured = [
        settings.default_llm_model,
        settings.chairman_model,
        settings.guard_model,
        *settings.council_model_list,
    ]
    models = sorted({m.removeprefix("ollama/") for m in configured if m.startswith("ollama/")})
    if not models:
        return "no ollama/-prefixed models configured"

    warmed: list[str] = []
    async with httpx.AsyncClient(timeout=90.0) as client:
        for name in models:
            try:
                resp = await client.post(
                    f"{settings.ollama_base_url}/api/generate",
                    json={
                        "model": name,
                        "prompt": "Hi",
                        "stream": False,
                        "keep_alive": settings.ollama_keep_alive,
                    },
                )
                resp.raise_for_status()
                warmed.append(name)
            except httpx.HTTPError as exc:
                logger.warning("Failed to warm Ollama model %r: %s", name, exc)

    return (
        f"warmed {len(warmed)}/{len(models)} model(s) (keep_alive={settings.ollama_keep_alive}): "
        f"{', '.join(warmed) or 'none'}"
    )


def check_vector_store_write() -> str:
    import numpy as np

    from app.stores.vector.chroma_store import get_vector_store

    store = get_vector_store()
    probe_id = "__preflight_probe__"
    store.add(
        ids=[probe_id],
        embeddings=np.zeros((1, 384), dtype=np.float32),
        documents=["preflight probe"],
        metadatas=[
            {"doc_id": "__preflight__", "parent_id": "", "strategy": "", "section_path": ""}
        ],
    )
    store.delete_by_doc("__preflight__")
    return "chroma read/write ok"


async def run_preflight() -> PreflightReport:
    """Runs every check concurrently (they're independent and each already offloads blocking
    work to a thread) and caches the report for /health to read. Never raises — a failed check
    is recorded, not propagated, so one missing model never prevents the server from starting
    at all (see docs/TROUBLESHOOTING.md on why "fails loud but doesn't boot" would be worse
    than "boots, reports what's wrong")."""
    global _last_report
    results = await asyncio.gather(
        timed_check("embedder", warm_embedder),
        timed_check("pii_detector", _warm_pii_detector),
        timed_check("docling_parser", _warm_docling),
        timed_check("reranker", _warm_reranker),
        timed_check("ollama", check_ollama),
        timed_check("ollama_models", warm_ollama_models),
        timed_check("vector_store", check_vector_store_write),
    )
    report = PreflightReport(checks=list(results), ran_at=time.time())
    _last_report = report
    for check in report.checks:
        level = logging.INFO if check.ok else logging.WARNING
        logger.log(
            level,
            "Preflight: %s %s (%.0fms) — %s",
            check.name,
            "OK" if check.ok else "FAILED",
            check.duration_ms,
            check.detail,
        )
    return report
