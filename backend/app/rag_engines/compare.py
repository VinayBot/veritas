"""Strategy comparison: "the default gets you X, this gets you Y" — measured, not asserted.

Each strategy is run over the same questions against the same document and scored by the
same judge (app/evaluation/benchmark.py). Deltas are differences between those runs and
nothing else: a delta is only reported for a metric both sides actually measured, it always
carries the number of questions it rests on, and under ten questions it is marked
indicative.

Results are cached per strategy, keyed by everything that could change them (the document's
chunks, the eval set or question, the models, the harness version), so reopening a
comparison re-runs nothing and adding one strategy to a comparison runs only that one.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.agents.models import ChatReport
from app.agents.orchestrator import answer_question, score_quality
from app.chunking.models import ChunkRow
from app.core.db import session_scope
from app.evaluation import service as evaluation_service
from app.evaluation.benchmark import (
    HARNESS_VERSION,
    MAX_AGENT_SAMPLES,
    MAX_EVAL_QUESTIONS,
    Checkpoint,
    ConfigResult,
    Progress,
    _noop_progress,
    run_strategies,
    skipped,
    strategy_concurrency,
)
from app.evaluation.datasets import load_dataset
from app.evaluation.models import ComparisonRun, StrategyEvaluation
from app.ingestion.models import Document
from app.rag_engines import availability
from app.rag_engines.registry import get_strategy

SMALL_SAMPLE = 10
# Below this difference in the comparison score, two strategies are treated as tied.
TIE_MARGIN = 0.02
# Rough judge overhead per question (three short scoring calls), used only in estimates.
JUDGE_SECONDS_PER_QUESTION = 3.0  # one combined judge call
MIN_MEASURED_RUNS = 3

# Higher is better for all of these except latency and tokens.
QUALITY_METRICS = ("faithfulness", "answer_relevancy", "correctness")
RETRIEVAL_METRICS = ("precision_at_5", "recall_at_5", "ndcg_at_5")
SCORE_WEIGHTS = {"faithfulness": 0.4, "correctness": 0.3, "answer_relevancy": 0.2, "ndcg_at_5": 0.1}


class ComparisonError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


async def corpus_hash(document_id: str) -> str:
    """Changes whenever the document's working index does (re-chunking, re-ingest)."""
    async with session_scope() as session:
        rows = await session.execute(
            select(ChunkRow.chunk_id)
            .where(ChunkRow.doc_id == document_id, ChunkRow.variant == "default")
            .order_by(ChunkRow.chunk_id)
        )
        ids = [r[0] for r in rows.all()]
    return hashlib.sha256("|".join(ids).encode()).hexdigest()


def cache_key(corpus: str, strategy: str, subject: str, run_config: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "corpus": corpus,
            "strategy": strategy,
            "subject": subject,
            "models": {
                k: run_config.get(k) for k in ("judge", "generator", "embedding", "reranker")
            },
            "harness": HARNESS_VERSION,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


async def _cached(key: str) -> StrategyEvaluation | None:
    async with session_scope() as session:
        return await session.get(StrategyEvaluation, key)


async def measured_latency_ms(strategy_id: str) -> tuple[float | None, int]:
    """Median answer latency of this strategy on this machine, from real chat turns, and how
    many turns that rests on."""
    async with session_scope() as session:
        rows = await session.execute(
            select(ChatReport.latency_ms).where(
                ChatReport.strategy == strategy_id,
                ChatReport.cache_hit.is_(False),
                ChatReport.latency_ms.is_not(None),
            )
        )
        values = sorted(float(r[0]) for r in rows.all() if r[0] is not None)
    if not values:
        return None, 0
    return values[len(values) // 2], len(values)


def _subject(dataset_id: str | None, query: str | None) -> str:
    return f"dataset:{dataset_id}" if dataset_id else f"query:{(query or '').strip().lower()}"


async def estimate(
    document_id: str, strategies: list[str], dataset_id: str | None, query: str | None
) -> dict[str, Any]:
    """What a comparison will cost before it starts: questions x strategies x latency, with
    cached results counted as free. Each latency says whether it was measured on this machine
    or is the registry's declared estimate."""
    n_questions = 1
    dataset_meta: dict[str, Any] | None = None
    if dataset_id:
        dataset = await evaluation_service.get_dataset(dataset_id)
        if dataset is None or dataset.document_id != document_id:
            raise ComparisonError(
                "dataset_not_found", f"No eval set {dataset_id} for this document"
            )
        n_questions = dataset.item_count
        dataset_meta = {
            "id": dataset.id,
            "version": dataset.version,
            "item_count": dataset.item_count,
        }

    run_config = await evaluation_service.current_run_config(document_id)
    corpus = await corpus_hash(document_id)
    subject = _subject(dataset_id, query)
    rows = []
    for strategy_id in strategies:
        spec = get_strategy(strategy_id)
        cap = MAX_AGENT_SAMPLES if spec.kind == "agentic" else MAX_EVAL_QUESTIONS
        questions = min(n_questions, cap)
        is_cached = await _cached(cache_key(corpus, strategy_id, subject, run_config)) is not None
        measured, n_runs = await measured_latency_ms(strategy_id)
        use_measured = measured is not None and n_runs >= MIN_MEASURED_RUNS
        per_question = ((measured if use_measured else spec.typical_latency_ms) or 0) / 1000
        seconds = 0.0 if is_cached else questions * (per_question + JUDGE_SECONDS_PER_QUESTION)
        rows.append(
            {
                "strategy": strategy_id,
                "questions": questions,
                "cached": is_cached,
                "latency_per_question_s": round(per_question, 1),
                "latency_source": f"measured over {n_runs} chat turns"
                if use_measured
                else "estimated",
                "estimated_seconds": round(seconds),
                "llm_calls": 0 if is_cached else questions * (spec.llm_calls + 1),
            }
        )
    parallel = strategy_concurrency()
    to_run = sorted(
        (float(r["estimated_seconds"]) for r in rows if not r["cached"]),  # type: ignore[arg-type]
        reverse=True,
    )
    # With N lanes, wall-clock time is roughly the busiest lane.
    lanes = [0.0] * parallel
    for seconds in to_run:
        lanes[lanes.index(min(lanes))] += seconds
    return {
        "document_id": document_id,
        "dataset": dataset_meta,
        "query": query,
        "strategies": rows,
        "questions": n_questions,
        "total_llm_calls": sum(r["llm_calls"] for r in rows),
        "estimated_seconds": round(max(lanes) if lanes else 0),
        "concurrency": parallel,
        "all_cached": all(r["cached"] for r in rows),
    }


async def _evaluate_single_query(strategy_id: str, document_id: str, query: str) -> ConfigResult:
    """One real question, no reference answer: what can be measured is the answer itself, its
    reference-free quality scores, latency and tokens. Correctness and retrieval metrics need
    ground truth and stay unmeasured."""
    turn = await answer_question(
        query, document_id, strategy_id, session_id=f"eval-{uuid.uuid4()}", detail="brief"
    )
    quality = await score_quality(turn)
    usage = turn.usage or {}
    complete_usage = bool(usage.get("llm_calls")) and not usage.get("calls_without_usage")
    return ConfigResult(
        name=strategy_id,
        retrieval_metrics={},
        faithfulness=quality["faithfulness"],
        answer_relevancy=quality["relevancy"],
        correctness=None,
        citation_validity=quality["citation_validity"],
        p50_latency_ms=turn.latency_ms,
        p95_latency_ms=turn.latency_ms,
        n_samples=1,
        n_judged={
            "faithfulness": int(quality["faithfulness"] is not None),
            "relevancy": int(quality["relevancy"] is not None),
            "correctness": 0,
        },
        avg_prompt_tokens=float(usage["prompt_tokens"]) if complete_usage else None,
        avg_completion_tokens=float(usage["completion_tokens"]) if complete_usage else None,
        avg_llm_calls=float(usage["llm_calls"]) if usage.get("llm_calls") is not None else None,
        samples=[
            {
                "item_id": "query",
                "category": "live",
                "question": query,
                "reference_answer": None,
                "answer": turn.answer,
                "outcome": turn.outcome,
                "citations": len(turn.citations),
                "latency_ms": round(turn.latency_ms, 1),
                "faithfulness": quality["faithfulness"],
                "relevancy": quality["relevancy"],
                "correctness": None,
                "citation_validity": quality["citation_validity"],
                "grounding": (quality["grounding"] or {}).get("score"),
            }
        ],
    )


def _metric(result: dict[str, Any], name: str) -> float | None:
    if name in RETRIEVAL_METRICS:
        return result.get("retrieval_metrics", {}).get(name)
    value = result.get(name)
    return float(value) if value is not None else None


def _judged_n(result: dict[str, Any], name: str) -> int:
    key = {"answer_relevancy": "relevancy"}.get(name, name)
    if name in QUALITY_METRICS:
        return int(result.get("n_judged", {}).get(key, 0))
    return int(result.get("n_samples", 0))


def compute_deltas(baseline: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Per-metric difference (other - baseline), only where both sides measured it."""
    deltas: dict[str, Any] = {}
    for name in (*QUALITY_METRICS, *RETRIEVAL_METRICS):
        base, value = _metric(baseline, name), _metric(other, name)
        n = min(_judged_n(baseline, name), _judged_n(other, name))
        if base is None or value is None or n == 0:
            continue
        deltas[name] = {
            "baseline": base,
            "value": value,
            "delta": value - base,
            "points": round((value - base) * 100, 1),
            "n": n,
            "small_sample": n < SMALL_SAMPLE,
        }
    n = min(int(baseline.get("n_samples", 0)), int(other.get("n_samples", 0)))
    if n:
        deltas["p50_latency_ms"] = {
            "baseline": baseline["p50_latency_ms"],
            "value": other["p50_latency_ms"],
            "delta": other["p50_latency_ms"] - baseline["p50_latency_ms"],
            "n": n,
            "small_sample": n < SMALL_SAMPLE,
        }
    base_tokens = _total_tokens(baseline)
    other_tokens = _total_tokens(other)
    if base_tokens is not None and other_tokens is not None:
        deltas["tokens_per_question"] = {
            "baseline": base_tokens,
            "value": other_tokens,
            "delta": other_tokens - base_tokens,
            "n": n,
            "small_sample": n < SMALL_SAMPLE,
        }
    return deltas


def _total_tokens(result: dict[str, Any]) -> float | None:
    prompt, completion = result.get("avg_prompt_tokens"), result.get("avg_completion_tokens")
    return None if prompt is None or completion is None else float(prompt) + float(completion)


def comparison_scores(results: list[dict[str, Any]]) -> tuple[dict[str, float], list[str]]:
    """One number per strategy from the metrics that every compared strategy measured,
    reweighted to sum to 1. Returns the scores and which metrics went into them."""
    usable = [name for name in SCORE_WEIGHTS if all(_metric(r, name) is not None for r in results)]
    if not usable:
        return {}, []
    total = sum(SCORE_WEIGHTS[name] for name in usable)
    return (
        {
            r["name"]: sum(SCORE_WEIGHTS[n] / total * (_metric(r, n) or 0.0) for n in usable)
            for r in results
        },
        usable,
    )


def _describe(deltas: dict[str, Any], baseline_name: str) -> str:
    labels = {
        "faithfulness": "faithfulness",
        "answer_relevancy": "relevancy",
        "correctness": "correctness",
        "precision_at_5": "precision@5",
        "recall_at_5": "recall@5",
    }
    parts = [
        f"{label} {deltas[name]['points']:+.1f} pts"
        for name, label in labels.items()
        if name in deltas and abs(deltas[name]["points"]) >= 0.1
    ]
    if "p50_latency_ms" in deltas:
        parts.append(f"latency {deltas['p50_latency_ms']['delta'] / 1000:+.1f}s")
    return (", ".join(parts) or "no measurable difference") + f" vs {baseline_name}"


def pick_winner(
    results: list[dict[str, Any]], baseline: str, deltas: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    ran = [r for r in results if not r.get("skipped_reason")]
    scores, used = comparison_scores(ran)
    if not scores or baseline not in scores:
        return None
    best = max(scores, key=lambda name: scores[name])
    margin = scores[best] - scores[baseline]
    n = min(int(r.get("n_samples", 0)) for r in ran)
    base_name = get_strategy(baseline).display_name
    if best == baseline or margin < TIE_MARGIN:
        return {
            "id": baseline,
            "is_baseline": True,
            "margin": round(max(margin, 0.0), 4),
            "scores": scores,
            "metrics_used": used,
            "n": n,
            "reason": (
                f"No strategy beat {base_name} by more than {TIE_MARGIN * 100:.0f} points on "
                f"{', '.join(used)} over {n} question{'s' if n != 1 else ''}; keep the default."
            ),
        }
    return {
        "id": best,
        "is_baseline": False,
        "margin": round(margin, 4),
        "scores": scores,
        "metrics_used": used,
        "n": n,
        "reason": (
            f"{get_strategy(best).display_name}: {_describe(deltas.get(best, {}), base_name)}, "
            f"measured over {n} question{'s' if n != 1 else ''}."
        ),
    }


async def run_comparison(
    document_id: str,
    strategies: list[str],
    *,
    dataset_id: str | None = None,
    query: str | None = None,
    baseline: str | None = None,
    progress: Progress = _noop_progress,
    checkpoint: Checkpoint | None = None,
) -> ComparisonRun:
    if bool(dataset_id) == bool(query and query.strip()):
        raise ComparisonError("invalid_comparison", "Give either an eval set or one question.")
    if baseline is None:
        from app.rag_engines.document_strategy import effective_strategy

        baseline = (await effective_strategy(document_id))[0]
    ordered = list(dict.fromkeys([baseline, *strategies]))  # the baseline is always measured
    for strategy_id in ordered:
        get_strategy(strategy_id)

    async with session_scope() as session:
        document = await session.get(Document, document_id)
    if document is None:
        raise ComparisonError("document_not_found", f"No document with id {document_id}")

    items = []
    dataset_meta: dict[str, Any] | None = None
    if dataset_id:
        dataset = await evaluation_service.get_dataset(dataset_id)
        if dataset is None or dataset.document_id != document_id:
            raise ComparisonError(
                "dataset_not_found", f"No eval set {dataset_id} for this document"
            )
        items = load_dataset(dataset.path)
        dataset_meta = {"id": dataset.id, "version": dataset.version, "item_count": len(items)}

    run_config = await evaluation_service.current_run_config(document_id)
    corpus = await corpus_hash(document_id)
    subject = _subject(dataset_id, query)
    keys = {s: cache_key(corpus, s, subject, run_config) for s in ordered}

    results: dict[str, dict[str, Any]] = {}
    cached_flags: dict[str, bool] = {}
    for strategy_id in ordered:
        hit = await _cached(keys[strategy_id])
        if hit is not None:
            results[strategy_id] = {**hit.result, "evaluated_at": hit.created_at.isoformat()}
            cached_flags[strategy_id] = True

    to_run = [s for s in ordered if s not in results]
    started = time.perf_counter()
    if to_run:
        fresh: list[ConfigResult]
        if dataset_id:
            fresh = await run_strategies(
                document_id, items, to_run, progress=progress, checkpoint=checkpoint
            )
        else:
            assert query is not None
            llm = await availability.llm_state()
            fresh = []
            for index, strategy_id in enumerate(to_run):
                if checkpoint is not None:
                    checkpoint()
                name = get_strategy(strategy_id).display_name
                await progress((index + 0.2) / len(to_run), f"{name}: answering")
                state = await availability.check(get_strategy(strategy_id), document, llm)
                if not state.available:
                    fresh.append(skipped(strategy_id, state.reason or "unavailable"))
                    continue
                fresh.append(await _evaluate_single_query(strategy_id, document_id, query.strip()))
        now = datetime.now(UTC)
        async with session_scope() as session:
            for result in fresh:
                results[result.name] = {**result.to_dict(), "evaluated_at": now.isoformat()}
                cached_flags[result.name] = False
                if result.skipped_reason:
                    continue  # never cache "could not run": the reason may be fixed next time
                session.add(
                    StrategyEvaluation(
                        cache_key=keys[result.name],
                        document_id=document_id,
                        strategy=result.name,
                        dataset_id=dataset_id,
                        query=query,
                        corpus_hash=corpus,
                        result=result.to_dict(),
                        run_config=run_config,
                        created_at=now,
                    )
                )
            await session.commit()

    await progress(1.0, "Comparing")
    ordered_results = [{**results[s], "cached": cached_flags[s]} for s in ordered]
    base_result = results[baseline]
    deltas = {
        s: compute_deltas(base_result, results[s])
        for s in ordered
        if s != baseline
        and not results[s].get("skipped_reason")
        and not base_result.get("skipped_reason")
    }
    n_queries = min(len(items), MAX_EVAL_QUESTIONS) if dataset_id else 1
    payload = {
        "document_id": document_id,
        "dataset": dataset_meta,
        "query": query.strip() if query else None,
        "baseline": baseline,
        "strategies": ordered_results,
        "deltas": deltas,
        "winner": pick_winner(ordered_results, baseline, deltas),
        "n_queries": n_queries,
        "small_sample": n_queries < SMALL_SAMPLE,
        "small_sample_note": (
            f"Indicative, small sample: n = {n_queries} (fewer than {SMALL_SAMPLE} questions)."
            if n_queries < SMALL_SAMPLE
            else None
        ),
        "run_config": run_config,
        "ran": to_run,
        "duration_ms": (time.perf_counter() - started) * 1000,
    }
    row = ComparisonRun(
        id=str(uuid.uuid4()),
        document_id=document_id,
        dataset_id=dataset_id,
        query=query.strip() if query else None,
        strategies=ordered,
        baseline=baseline,
        result=payload,
        created_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(row)
        await session.commit()
    return row


async def get_comparison(comparison_id: str) -> ComparisonRun | None:
    async with session_scope() as session:
        return await session.get(ComparisonRun, comparison_id)


async def latest_comparisons(document_id: str, limit: int = 10) -> list[ComparisonRun]:
    async with session_scope() as session:
        rows = await session.execute(
            select(ComparisonRun)
            .where(ComparisonRun.document_id == document_id)
            .order_by(ComparisonRun.created_at.desc())
            .limit(limit)
        )
        return list(rows.scalars().all())
