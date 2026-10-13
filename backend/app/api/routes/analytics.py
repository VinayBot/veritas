"""GET /api/v1/analytics/overview — the Dashboard's numbers, each computed from rows that
already exist: documents and chunks, persisted chat reports and runs, and the guardrail
audit log. Where a figure only exists for newer rows (stage timings, token counts, strategy
names) the response says how many rows it rests on rather than implying full coverage.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.agents.models import ChatReport, ChatRun
from app.api.routes.audit import audit_summary
from app.chunking.models import ChunkRow
from app.core.config import get_settings
from app.core.db import session_scope
from app.ingestion.models import Document
from app.llm.models_config import get_model_config
from app.rag_engines.registry import STRATEGIES, strategy_for_report

router = APIRouter(tags=["analytics"])

MAX_REPORTS = 5_000


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(int(len(ordered) * p), len(ordered) - 1)]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _dir_bytes(path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


async def _corpus() -> dict[str, Any]:
    settings = get_settings()
    async with session_scope() as session:
        by_status = dict(
            (
                await session.execute(
                    select(Document.status, func.count()).group_by(Document.status)
                )
            ).all()
        )
        chunks, tokens = (
            await session.execute(
                select(func.count(), func.coalesce(func.sum(ChunkRow.token_count), 0)).where(
                    ChunkRow.variant == "default"
                )
            )
        ).one()
        variant_chunks = (
            await session.execute(
                select(func.count()).select_from(ChunkRow).where(ChunkRow.variant != "default")
            )
        ).scalar_one()
        last = (
            await session.execute(
                select(Document.filename, Document.created_at)
                .order_by(Document.created_at.desc())
                .limit(1)
            )
        ).first()
    database = settings.data_dir / "veritas.db"
    return {
        "documents": int(sum(by_status.values())),
        "documents_by_status": {k: int(v) for k, v in by_status.items()},
        "chunks": int(chunks),
        "variant_chunks": int(variant_chunks),
        "tokens": int(tokens),
        "index_bytes": {
            "vectors": _dir_bytes(settings.data_dir / "chroma"),
            "database": database.stat().st_size if database.exists() else 0,
            "graph": (settings.data_dir / "graph.pickle").stat().st_size
            if (settings.data_dir / "graph.pickle").exists()
            else 0,
        },
        "embedding_model": get_model_config().embedding,
        "last_ingest": {"filename": last[0], "at": last[1].isoformat()} if last else None,
    }


@router.get("/analytics/overview")
async def overview(days: int = 14) -> dict:
    days = max(1, min(days, 90))
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    async with session_scope() as session:
        reports = list(
            (
                await session.execute(
                    select(ChatReport)
                    .where(ChatReport.created_at >= since)
                    .order_by(ChatReport.created_at.desc())
                    .limit(MAX_REPORTS)
                )
            )
            .scalars()
            .all()
        )
        total_reports = (
            await session.execute(select(func.count()).select_from(ChatReport))
        ).scalar_one()
        run_rows = (
            await session.execute(
                select(ChatRun.status, ChatRun.attempt).where(ChatRun.created_at >= since)
            )
        ).all()

    # ---- volume and quality per day ----
    by_day: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    volume: Counter = Counter()
    for r in reports:
        day = r.created_at.date().isoformat()
        volume[day] += 1
        quality = r.quality or {}
        for key in ("faithfulness", "relevancy"):
            if quality.get(key) is not None:
                by_day[day][key].append(float(quality[key]))
        grounding = (quality.get("grounding") or {}).get("score")
        if grounding is not None:
            by_day[day]["grounding"].append(float(grounding))
        by_day[day]["citations"].append(float(len(r.citations or [])))
        by_day[day]["zero_citation"].append(0.0 if r.citations else 1.0)
    days_sorted = sorted(volume)
    trend = [
        {
            "date": day,
            "queries": volume[day],
            "faithfulness": _mean(by_day[day]["faithfulness"]),
            "faithfulness_n": len(by_day[day]["faithfulness"]),
            "grounding": _mean(by_day[day]["grounding"]),
            "grounding_n": len(by_day[day]["grounding"]),
            "relevancy": _mean(by_day[day]["relevancy"]),
            "zero_citation_rate": _mean(by_day[day]["zero_citation"]),
            "avg_citations": _mean(by_day[day]["citations"]),
        }
        for day in days_sorted
    ]

    # ---- strategy mix and latency ----
    answered = [r for r in reports if not r.cache_hit]
    mix: Counter = Counter(strategy_for_report(r.strategy, r.mode) for r in reports)
    latency_by_strategy: dict[str, list[float]] = defaultdict(list)
    stage_durations: dict[str, list[float]] = defaultdict(list)
    timed_reports = 0
    tokens: list[float] = []
    for r in answered:
        if r.latency_ms is not None:
            latency_by_strategy[strategy_for_report(r.strategy, r.mode)].append(float(r.latency_ms))
        if r.timings:
            timed_reports += 1
            for stage in r.timings:
                if stage.get("duration_ms") is not None:
                    stage_durations[stage["stage"]].append(float(stage["duration_ms"]))
        usage = r.usage or {}
        if usage.get("llm_calls") and not usage.get("calls_without_usage"):
            tokens.append(float(usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)))
    all_latencies = [v for values in latency_by_strategy.values() for v in values]

    # ---- failures and retries ----
    statuses = Counter(status for status, _ in run_rows)
    retried = sum(1 for _, attempt in run_rows if (attempt or 1) > 1)
    looped = [r for r in reports if (r.loops or {}).get("critic_loops", 0) > 0]
    revised = [r for r in reports if (r.loops or {}).get("revisions", 0) > 0]
    with_loops = [r for r in reports if r.loops is not None]

    citations = [float(len(r.citations or [])) for r in reports]
    zero = [r for r in reports if not r.citations and (r.outcome or "done") == "done"]
    finished = [r for r in reports if (r.outcome or "done") == "done"]

    return {
        "window_days": days,
        "generated_at": datetime.now(UTC).isoformat(),
        "corpus": await _corpus(),
        "queries": {
            "in_window": len(reports),
            "all_time": int(total_reports),
            "cache_hits": sum(1 for r in reports if r.cache_hit),
            "by_day": trend,
            "latency_ms": {
                "p50": _percentile(all_latencies, 0.5),
                "p95": _percentile(all_latencies, 0.95),
                "n": len(all_latencies),
            },
            "latency_by_strategy": [
                {
                    "strategy": name,
                    "display_name": STRATEGIES[name].display_name if name in STRATEGIES else name,
                    "p50": _percentile(values, 0.5),
                    "p95": _percentile(values, 0.95),
                    "n": len(values),
                }
                for name, values in sorted(latency_by_strategy.items())
            ],
            "latency_by_stage": [
                {
                    "stage": stage,
                    "p50": _percentile(values, 0.5),
                    "p95": _percentile(values, 0.95),
                    "n": len(values),
                }
                for stage, values in sorted(
                    stage_durations.items(), key=lambda kv: -(_percentile(kv[1], 0.5) or 0)
                )
            ],
            # Stage timings and token counts are only recorded on reports written since they
            # were introduced.
            "reports_with_stage_timings": timed_reports,
            "avg_tokens_per_answer": _mean(tokens),
            "reports_with_token_counts": len(tokens),
            "strategy_mix": [
                {
                    "strategy": name,
                    "display_name": STRATEGIES[name].display_name if name in STRATEGIES else name,
                    "count": count,
                    "share": count / len(reports),
                }
                for name, count in mix.most_common()
            ],
        },
        "reliability": {
            "runs": len(run_rows),
            "failed": statuses.get("failed", 0),
            "cancelled": statuses.get("cancelled", 0),
            "blocked": statuses.get("blocked", 0),
            "abstained": statuses.get("abstained", 0),
            "retried_after_timeout": retried,
            "failure_rate": statuses.get("failed", 0) / len(run_rows) if run_rows else None,
            "retry_rate": retried / len(run_rows) if run_rows else None,
            # From the agent's bounded loops; recorded on newer reports only.
            "critic_retry_turns": len(looped),
            "revision_turns": len(revised),
            "turns_with_loop_data": len(with_loops),
            "agent_retry_rate": (
                len({r.id for r in looped} | {r.id for r in revised}) / len(with_loops)
            )
            if with_loops
            else None,
        },
        "quality": {
            "faithfulness": _mean([v for d in trend for v in by_day[d["date"]]["faithfulness"]]),
            "grounding": _mean([v for d in trend for v in by_day[d["date"]]["grounding"]]),
            "relevancy": _mean([v for d in trend for v in by_day[d["date"]]["relevancy"]]),
            "zero_citation_rate": len(zero) / len(finished) if finished else None,
            "zero_citation_answers": len(zero),
            "answered": len(finished),
            "avg_citations": _mean(citations),
        },
        "guardrails": (await audit_summary()).model_dump(mode="json"),
    }
