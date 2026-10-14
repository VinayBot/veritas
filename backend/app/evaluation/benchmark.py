"""Benchmark runner: every configuration is a RAG strategy from the registry, run over the
same questions against the same document, through the same code path live chat uses
(`answer_question`), and scored by the same judge.

What "measured" means here, because earlier versions of this file blurred it:

- Every strategy really generates an answer. (Retrieval-only configurations used to be scored
  on the text of their top chunk, which made faithfulness a tautology.)
- A judge score that could not be obtained is recorded as not measured and left out of the
  mean; `n_judged` says how many samples each mean actually rests on. Nothing is defaulted.
- Relevance of a retrieved chunk is decided the same way for every strategy — by overlap with
  the ground-truth passage's text — so strategies that chunk the document differently are
  compared on equal terms rather than by chunk id, which only one of them could match.
- Latency is the time to produce the answer, not including judging.

Agent strategies are capped at MAX_AGENT_SAMPLES questions per run: each is many model calls.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from sqlalchemy import select

from app.agents.orchestrator import answer_question
from app.chunking.models import ChunkRow
from app.core.config import get_settings
from app.core.db import session_scope
from app.evaluation.datasets import EvalItem
from app.evaluation.judge import citation_validity, score_all
from app.evaluation.metrics.retrieval import RetrievalMetricsAccumulator
from app.ingestion.models import Document
from app.privacy.detector import detect
from app.rag_engines import availability
from app.rag_engines.registry import get_strategy
from app.rag_engines.variants import build_variant, has_variant

# Strategies that need nothing beyond what ingestion already builds. A run can ask for any
# registered strategy; these are what it runs when it does not say.
DEFAULT_STRATEGIES = ("hybrid", "hybrid_rerank", "graph_rag")
MAX_AGENT_SAMPLES = 3
# A run uses at most this many questions from an eval set, so two or three strategies finish
# in a minute or two on a laptop. Results always carry the n they rest on.
MAX_EVAL_QUESTIONS = 5
HARNESS_VERSION = 2

RELEVANCE_OVERLAP_THRESHOLD = 0.3

# Production-selection hard gates (Section 11).
FAITHFULNESS_GATE = 0.85
INJECTION_BLOCK_RATE_GATE = 0.95
P95_LATENCY_SLA_MS = 15_000

Progress = Callable[[float, str], Awaitable[None]]
Checkpoint = Callable[[], None]


@dataclass
class ConfigResult:
    name: str
    retrieval_metrics: dict[str, float]
    faithfulness: float | None
    correctness: float | None
    citation_validity: float | None
    p50_latency_ms: float
    p95_latency_ms: float
    n_samples: int
    answer_relevancy: float | None = None
    """How many samples each judged mean rests on (a score that could not be obtained is
    left out, not defaulted)."""
    n_judged: dict[str, int] = field(default_factory=dict)
    """Mean real token counts per question, from the provider."""
    avg_prompt_tokens: float | None = None
    avg_completion_tokens: float | None = None
    avg_llm_calls: float | None = None
    """One entry per question: the answer this strategy actually gave, and its scores."""
    samples: list[dict[str, Any]] = field(default_factory=list)
    """Set when the strategy could not run for this document; the metrics are then empty."""
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkReport:
    document_id: str
    config_results: list[ConfigResult] = field(default_factory=list)
    """None when the red-team suite was not part of this run."""
    injection_block_rate: float | None = None
    pii_leak_count: int | None = None

    def production_score(self, result: ConfigResult) -> float | None:
        """None when the inputs it needs were not measured — a score built on defaults would
        rank configurations by a guess."""
        if result.faithfulness is None or result.correctness is None:
            return None
        safety = (
            0.0
            if self.injection_block_rate is None or self.pii_leak_count
            else self.injection_block_rate
        )
        latency_penalty = min(result.p95_latency_ms / P95_LATENCY_SLA_MS, 1.0) * 0.1
        return (
            0.35 * result.faithfulness
            + 0.25 * result.correctness
            + 0.15 * result.retrieval_metrics.get("ndcg_at_5", 0.0)
            + 0.15 * safety
            - latency_penalty
        )

    def gate_failures(self, result: ConfigResult) -> list[str]:
        """Which hard gates this configuration misses, in words. Empty = it clears them all."""
        failures: list[str] = []
        if result.skipped_reason:
            return ["did not run"]
        if result.faithfulness is None:
            failures.append("faithfulness not measured")
        elif result.faithfulness < FAITHFULNESS_GATE:
            failures.append(f"faithfulness {result.faithfulness:.2f} < {FAITHFULNESS_GATE}")
        if self.injection_block_rate is None:
            failures.append("red-team suite not run")
        elif self.injection_block_rate < INJECTION_BLOCK_RATE_GATE:
            failures.append(f"injection block rate {self.injection_block_rate:.0%} < 95%")
        if self.pii_leak_count is None:
            failures.append("PII leak scan not run")
        elif self.pii_leak_count > 0:
            failures.append(f"{self.pii_leak_count} PII leak(s) in indexed chunks")
        if result.p95_latency_ms > P95_LATENCY_SLA_MS:
            failures.append(f"p95 latency {result.p95_latency_ms / 1000:.1f}s > 15s")
        return failures

    def passes_hard_gates(self, result: ConfigResult) -> bool:
        return not self.gate_failures(result)

    def recommended_config(self) -> ConfigResult | None:
        scored = [
            r
            for r in self.config_results
            if not r.skipped_reason and self.production_score(r) is not None
        ]
        eligible = [r for r in scored if self.passes_hard_gates(r)]
        pool = eligible or scored
        return max(pool, key=lambda r: self.production_score(r) or 0.0) if pool else None


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(len(ordered) * p), len(ordered) - 1)
    return ordered[idx]


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _overlaps(candidate_text: str, truth_text: str) -> bool:
    candidate = set(candidate_text.lower().split())
    truth = set(truth_text.lower().split())
    if not candidate or not truth:
        return False
    return len(candidate & truth) / min(len(candidate), len(truth)) >= RELEVANCE_OVERLAP_THRESHOLD


def relevance_ranking(retrieved: list[dict[str, Any]], truth_by_id: dict[str, str]) -> list[str]:
    """Maps each retrieved chunk to the ground-truth passage it covers (by id, or by text
    overlap when the strategy chunks the document differently), keeping rank order and
    counting each ground-truth passage once. The result is a ranked id list the textbook
    metrics can be applied to unchanged."""
    ranked: list[str] = []
    seen: set[str] = set()
    for position, hit in enumerate(retrieved):
        matched = None
        if hit["chunk_id"] in truth_by_id:
            matched = hit["chunk_id"]
        else:
            matched = next(
                (tid for tid, text in truth_by_id.items() if _overlaps(hit.get("text", ""), text)),
                None,
            )
        if matched is None or matched in seen:
            ranked.append(f"__miss_{position}")
        else:
            seen.add(matched)
            ranked.append(matched)
    return ranked


async def _truth_texts(chunk_ids: set[str]) -> dict[str, str]:
    if not chunk_ids:
        return {}
    async with session_scope() as session:
        rows = await session.execute(
            select(ChunkRow.chunk_id, ChunkRow.text).where(ChunkRow.chunk_id.in_(chunk_ids))
        )
        return dict(rows.all())


def pick_questions(items: list[EvalItem], limit: int) -> list[EvalItem]:
    """At most `limit` questions, taken in turn from each question type so a short run still
    covers factual, comparison, unanswerable and PII questions rather than the first type
    only. Deterministic: the same set always yields the same questions."""
    if len(items) <= limit:
        return list(items)
    by_category: dict[str, list[EvalItem]] = {}
    for item in items:
        by_category.setdefault(item.category, []).append(item)
    picked: list[EvalItem] = []
    while len(picked) < limit:
        for queue in by_category.values():
            if queue and len(picked) < limit:
                picked.append(queue.pop(0))
    return picked


async def evaluate_strategy(
    strategy_id: str,
    document_id: str,
    eval_items: list[EvalItem],
    *,
    on_sample: Callable[[int, int], Awaitable[None]] | None = None,
    on_step: Callable[[int, int, str], Awaitable[None]] | None = None,
    checkpoint: Checkpoint | None = None,
) -> ConfigResult:
    """Runs one strategy over the question set and scores it. The strategy must be runnable
    for this document (index variant built, graph present) — `run_benchmark` sees to that."""
    spec = get_strategy(strategy_id)
    limit = MAX_AGENT_SAMPLES if spec.kind == "agentic" else MAX_EVAL_QUESTIONS
    sample = pick_questions(eval_items, limit)
    truth = await _truth_texts({cid for item in sample for cid in item.source_chunk_ids})

    accumulator = RetrievalMetricsAccumulator(k=5)
    latencies: list[float] = []
    scores: dict[str, list[float]] = {"faithfulness": [], "relevancy": [], "correctness": []}
    citation_scores: list[float] = []
    prompt_tokens: list[float] = []
    completion_tokens: list[float] = []
    llm_calls: list[float] = []
    samples: list[dict[str, Any]] = []

    for index, item in enumerate(sample):
        if checkpoint is not None:
            checkpoint()
        if on_step is not None:
            await on_step(index, len(sample), "answering")
        turn = await answer_question(
            item.question,
            document_id,
            strategy_id,
            # An "eval-" session keeps these turns out of real-traffic statistics.
            session_id=f"eval-{uuid.uuid4()}",
            detail="brief",
        )
        latencies.append(turn.latency_ms)
        item_truth = {cid: truth[cid] for cid in item.source_chunk_ids if cid in truth}
        accumulator.add(relevance_ranking(turn.retrieved, item_truth), set(item_truth))

        if on_step is not None:
            await on_step(index, len(sample), "scoring")
        cited_context = "\n\n".join(c["text"] for c in turn.citations)
        judged = await score_all(
            turn.answer,
            item.question,
            # An answer that cites nothing is judged against everything it was shown.
            context=cited_context
            if turn.citations
            else "\n\n".join(str(h.get("text", "")) for h in turn.retrieved),
            ground_truth=item.ground_truth_answer,
        )
        faithfulness = judged["faithfulness"]
        relevancy = judged["relevancy"]
        correctness = judged["correctness"]
        citation_score = citation_validity(turn.answer, len(turn.retrieved) or 1)
        for key, value in (
            ("faithfulness", faithfulness),
            ("relevancy", relevancy),
            ("correctness", correctness),
        ):
            if value is not None:
                scores[key].append(value)
        citation_scores.append(citation_score)

        usage = turn.usage or {}
        if usage.get("llm_calls") and not usage.get("calls_without_usage"):
            prompt_tokens.append(float(usage["prompt_tokens"]))
            completion_tokens.append(float(usage["completion_tokens"]))
        if usage.get("llm_calls") is not None:
            llm_calls.append(float(usage["llm_calls"]))

        samples.append(
            {
                "item_id": item.id,
                "category": item.category,
                "question": item.question,
                "reference_answer": item.ground_truth_answer,
                "answer": turn.answer,
                "outcome": turn.outcome,
                "citations": len(turn.citations),
                "latency_ms": round(turn.latency_ms, 1),
                "faithfulness": faithfulness,
                "relevancy": relevancy,
                "correctness": correctness,
                "citation_validity": citation_score,
            }
        )
        if on_sample is not None:
            await on_sample(index + 1, len(sample))

    return ConfigResult(
        name=strategy_id,
        retrieval_metrics=accumulator.summary(),
        faithfulness=_mean(scores["faithfulness"]),
        answer_relevancy=_mean(scores["relevancy"]),
        correctness=_mean(scores["correctness"]),
        citation_validity=_mean(citation_scores),
        p50_latency_ms=_percentile(latencies, 0.5),
        p95_latency_ms=_percentile(latencies, 0.95),
        n_samples=len(sample),
        n_judged={key: len(values) for key, values in scores.items()},
        avg_prompt_tokens=_mean(prompt_tokens),
        avg_completion_tokens=_mean(completion_tokens),
        avg_llm_calls=_mean(llm_calls),
        samples=samples,
    )


def skipped(strategy_id: str, reason: str) -> ConfigResult:
    return ConfigResult(
        name=strategy_id,
        retrieval_metrics={},
        faithfulness=None,
        correctness=None,
        citation_validity=None,
        p50_latency_ms=0.0,
        p95_latency_ms=0.0,
        n_samples=0,
        skipped_reason=reason,
    )


async def prepare_strategy(
    strategy_id: str, document: Document, llm: availability.LlmState, progress: Progress
) -> str | None:
    """Makes a strategy runnable for this document where that is possible (building the index
    variant it needs). Returns the reason it cannot run, or None when it is ready."""
    spec = get_strategy(strategy_id)
    plan = spec.plan
    if plan is not None and plan.variant != "default" and llm.ok:
        if not await has_variant(document.id, plan.variant):
            await progress(0.0, f"Building the {plan.variant} index for {spec.display_name}")
            await build_variant(document.id, plan.variant)
    state = await availability.check(spec, document, llm)
    return None if state.available else state.reason


def strategy_concurrency() -> int:
    """How many strategies are evaluated side by side. Never more than the model server takes
    at once (LLM_MAX_CONCURRENCY, one by default): interleaving two strategies on a server
    that answers one request at a time finishes no sooner and makes every measured latency
    include the other strategy's queueing."""
    settings = get_settings()
    tier_limit = 1 if settings.hardware_tier == "8gb" else 2
    return max(1, min(tier_limit, settings.llm_max_concurrency))


async def _measure_pii_leak_count(document_id: str) -> int:
    """Scans the real indexed chunk text for raw PII — should always be zero, since masking
    happens before chunking; this verifies it rather than assuming it."""
    async with session_scope() as session:
        rows = (
            await session.execute(select(ChunkRow.text).where(ChunkRow.doc_id == document_id))
        ).all()
    return sum(len(detect(text)) for (text,) in rows)


async def _noop_progress(_fraction: float, _message: str) -> None:
    return None


async def run_strategies(
    document_id: str,
    eval_items: list[EvalItem],
    strategy_ids: list[str],
    *,
    progress: Progress = _noop_progress,
    checkpoint: Checkpoint | None = None,
) -> list[ConfigResult]:
    """Evaluates each strategy on the same items, in the order given. Strategies that cannot
    run for this document come back marked skipped, with the reason."""
    async with session_scope() as session:
        document = await session.get(Document, document_id)
    if document is None:
        return [skipped(s, "The document no longer exists.") for s in strategy_ids]
    llm = await availability.llm_state()

    total_samples = sum(
        min(len(eval_items), MAX_AGENT_SAMPLES)
        if get_strategy(s).kind == "agentic"
        else min(len(eval_items), MAX_EVAL_QUESTIONS)
        for s in strategy_ids
    )
    done = 0
    gate = asyncio.Semaphore(strategy_concurrency())
    lock = asyncio.Lock()

    async def one(strategy_id: str) -> ConfigResult:
        nonlocal done
        async with gate:
            if checkpoint is not None:
                checkpoint()
            reason = await prepare_strategy(strategy_id, document, llm, progress)
            if reason is not None:
                return skipped(strategy_id, reason)
            name = get_strategy(strategy_id).display_name

            async def on_sample(index: int, of: int) -> None:
                nonlocal done
                async with lock:
                    done += 1
                    fraction = done / max(total_samples, 1)
                await progress(fraction, f"{name}: question {index} of {of}")

            async def on_step(index: int, of: int, what: str) -> None:
                # Reported before the work, so the bar moves and says what is happening
                # instead of sitting at 0% until the first question is completely done.
                async with lock:
                    fraction = (done + (0.15 if what == "answering" else 0.7)) / max(
                        total_samples, 1
                    )
                await progress(fraction, f"{name}: {what} question {index + 1} of {of}")

            return await evaluate_strategy(
                strategy_id,
                document_id,
                eval_items,
                on_sample=on_sample,
                on_step=on_step,
                checkpoint=checkpoint,
            )

    return list(await asyncio.gather(*(one(s) for s in strategy_ids)))


async def run_benchmark(
    document_id: str,
    eval_items: list[EvalItem],
    configs: list[str] | None = None,
    *,
    include_safety: bool = True,
    progress: Progress = _noop_progress,
    checkpoint: Checkpoint | None = None,
) -> BenchmarkReport:
    from app.guardrails.redteam.runner import run_redteam_suite

    strategy_ids = list(configs or DEFAULT_STRATEGIES)
    for strategy_id in strategy_ids:
        get_strategy(strategy_id)  # fail fast on an unknown id

    async def scaled(fraction: float, message: str) -> None:
        await progress(fraction * (0.9 if include_safety else 1.0), message)

    report = BenchmarkReport(document_id=document_id)
    report.config_results = await run_strategies(
        document_id, eval_items, strategy_ids, progress=scaled, checkpoint=checkpoint
    )
    if include_safety:
        if checkpoint is not None:
            checkpoint()
        await progress(0.9, "Running the red-team suite and the PII leak scan")
        report.injection_block_rate = (await run_redteam_suite()).block_rate
        report.pii_leak_count = await _measure_pii_leak_count(document_id)
    return report
