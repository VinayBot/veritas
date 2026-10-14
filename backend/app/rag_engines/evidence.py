"""What has actually been measured about strategies on one document.

The rule-based advisor (advisor.py) predicts a strategy from the document's shape. Once a
comparison or an evaluation has run the strategies on questions with known answers, that
measurement is better evidence than any prediction, and the recommendation should follow it.
Only runs on a question set count: a single-question comparison is too small to rank on.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.db import session_scope
from app.evaluation.models import BenchmarkRun, ComparisonRun
from app.rag_engines.compare import SMALL_SAMPLE, TIE_MARGIN, comparison_scores
from app.rag_engines.registry import STRATEGIES

CURRENT_HARNESS = 2


def _ran(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in results if not r.get("skipped_reason") and r.get("name") in STRATEGIES]


async def _measured_runs(document_id: str) -> list[dict[str, Any]]:
    """Every question-set run on this document that measured at least two strategies,
    newest first, in one shape whichever page started it."""
    runs: list[dict[str, Any]] = []
    async with session_scope() as session:
        comparisons = (
            await session.execute(
                select(ComparisonRun).where(
                    ComparisonRun.document_id == document_id,
                    ComparisonRun.dataset_id.is_not(None),
                )
            )
        ).scalars()
        for row in comparisons:
            ran = _ran(row.result.get("strategies", []))
            if len(ran) >= 2:
                runs.append(
                    {
                        "source": "comparison",
                        "id": row.id,
                        "created_at": row.created_at,
                        "results": ran,
                        "n": int(row.result.get("n_queries") or 0),
                    }
                )
        benchmarks = (
            await session.execute(
                select(BenchmarkRun).where(
                    BenchmarkRun.document_id == document_id,
                    BenchmarkRun.harness_version == CURRENT_HARNESS,
                )
            )
        ).scalars()
        for bench in benchmarks:
            ran = _ran(bench.config_results)
            if len(ran) >= 2:
                runs.append(
                    {
                        "source": "evaluation",
                        "id": bench.id,
                        "created_at": bench.created_at,
                        "results": ran,
                        "n": min(int(r.get("n_samples") or 0) for r in ran),
                    }
                )
    runs.sort(key=lambda r: r["created_at"] or datetime.min, reverse=True)
    return runs


async def measured_evidence(document_id: str, prefer: str | None = None) -> dict[str, Any] | None:
    """The most recent measurement, preferring one that included `prefer` (the strategy the
    rules picked), ranked by the same composite score a comparison uses. None if nothing on
    a question set has been measured for this document."""
    runs = await _measured_runs(document_id)
    if not runs:
        return None
    chosen = next(
        (r for r in runs if prefer and any(x["name"] == prefer for x in r["results"])), runs[0]
    )
    scores, metrics = comparison_scores(chosen["results"])
    if not scores:
        return None
    ranking = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    margin = ranking[0][1] - ranking[1][1] if len(ranking) > 1 else 0.0
    return {
        "source": chosen["source"],
        "run_id": chosen["id"],
        "created_at": chosen["created_at"].isoformat() if chosen["created_at"] else None,
        "n": chosen["n"],
        "small_sample": chosen["n"] < SMALL_SAMPLE,
        "metrics_used": metrics,
        "ranking": [
            {
                "strategy": name,
                "display_name": STRATEGIES[name].display_name,
                "score": round(score, 4),
            }
            for name, score in ranking
        ],
        "winner": ranking[0][0],
        "margin": round(margin, 4),
        "clear": margin >= TIE_MARGIN,
        "measured": [name for name, _ in ranking],
    }
