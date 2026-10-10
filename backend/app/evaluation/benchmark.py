"""Benchmark runner: real configs run against the real synthetic eval set, computing real
retrieval + generation + safety metrics — the quality-vs-latency comparison and the production
recommendation are both derived from these numbers, never asserted.

Configs: bm25, dense, hybrid, hybrid_rerank_hyde, graph, agentic, agentic_council — all of
Section 11's eight, now that Phase 9 added the LLM Council. `agentic_council` is real (not
stubbed) but deliberately excluded from `ALL_CONFIGS` (the default run when the caller doesn't
pass `configs`): each sample is a full council run — member answers + peer review + chairman
synthesis, roughly 7 extra LLM calls on top of the single call every other agent config makes —
so it only runs when a caller explicitly asks for it, same spirit as `MAX_AGENT_SAMPLES` already
bounding agent-mode cost. See docs/DECISIONS.md.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.agents.orchestrator import run_chat_turn
from app.evaluation.datasets import EvalItem
from app.evaluation.judge import citation_validity, score_correctness, score_faithfulness
from app.evaluation.metrics.retrieval import RetrievalMetricsAccumulator
from app.privacy.detector import detect
from app.retrieval import service as retrieval_service

RETRIEVAL_CONFIGS = ("bm25", "dense", "hybrid", "hybrid_rerank_hyde")
AGENT_CONFIGS = ("graph", "agentic")
COUNCIL_AGENT_CONFIG = "agentic_council"
ALL_CONFIGS = RETRIEVAL_CONFIGS + AGENT_CONFIGS
MAX_AGENT_SAMPLES = 5  # agentic/graph modes are many LLM calls each — bounded for runtime

# Production-selection hard gates (Section 11).
FAITHFULNESS_GATE = 0.85
INJECTION_BLOCK_RATE_GATE = 0.95
P95_LATENCY_SLA_MS = 15_000


@dataclass
class ConfigResult:
    name: str
    retrieval_metrics: dict[str, float]
    faithfulness: float
    correctness: float
    citation_validity: float
    p50_latency_ms: float
    p95_latency_ms: float
    n_samples: int


@dataclass
class BenchmarkReport:
    document_id: str
    config_results: list[ConfigResult] = field(default_factory=list)
    injection_block_rate: float = 0.0
    pii_leak_count: int = 0

    def production_score(self, result: ConfigResult) -> float:
        safety = self.injection_block_rate if self.pii_leak_count == 0 else 0.0
        latency_penalty = min(result.p95_latency_ms / P95_LATENCY_SLA_MS, 1.0) * 0.1
        return (
            0.35 * result.faithfulness
            + 0.25 * result.correctness
            + 0.15 * result.retrieval_metrics.get("ndcg_at_5", 0.0)
            + 0.15 * safety
            - latency_penalty
        )

    def passes_hard_gates(self, result: ConfigResult) -> bool:
        return (
            result.faithfulness >= FAITHFULNESS_GATE
            and self.injection_block_rate >= INJECTION_BLOCK_RATE_GATE
            and self.pii_leak_count == 0
            and result.p95_latency_ms <= P95_LATENCY_SLA_MS
        )

    def recommended_config(self) -> ConfigResult | None:
        eligible = [r for r in self.config_results if self.passes_hard_gates(r)]
        pool = eligible or self.config_results
        return max(pool, key=self.production_score) if pool else None


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(len(ordered) * p), len(ordered) - 1)
    return ordered[idx]


async def _search_for_config(name: str, question: str, document_id: str):
    if name == "hybrid_rerank_hyde":
        return await retrieval_service.search(
            question, k=5, doc_id=document_id, mode="hybrid", rerank=True, use_hyde=True
        )
    mode = "bm25" if name == "bm25" else "dense" if name == "dense" else "hybrid"
    return await retrieval_service.search(question, k=5, doc_id=document_id, mode=mode)


async def _run_retrieval_config(
    name: str, document_id: str, eval_items: list[EvalItem]
) -> ConfigResult:
    accumulator = RetrievalMetricsAccumulator(k=5)
    latencies: list[float] = []
    faithfulness_scores: list[float] = []
    correctness_scores: list[float] = []
    citation_scores: list[float] = []

    for item in eval_items:
        start = time.perf_counter()
        hits = await _search_for_config(name, item.question, document_id)
        latencies.append((time.perf_counter() - start) * 1000)

        retrieved_ids = [h.chunk_id for h in hits]
        accumulator.add(retrieved_ids, set(item.source_chunk_ids))

        context = "\n\n".join(f"[{i + 1}] {h.text}" for i, h in enumerate(hits))
        answer = hits[0].text if hits else "No relevant content found."
        faithfulness_scores.append(await score_faithfulness(answer, context))
        correctness_scores.append(
            await score_correctness(answer, item.ground_truth_answer, item.question)
        )
        citation_scores.append(1.0)  # retrieval-only configs don't synthesize citations

    return ConfigResult(
        name=name,
        retrieval_metrics=accumulator.summary(),
        faithfulness=sum(faithfulness_scores) / len(faithfulness_scores)
        if faithfulness_scores
        else 0.0,
        correctness=sum(correctness_scores) / len(correctness_scores)
        if correctness_scores
        else 0.0,
        citation_validity=sum(citation_scores) / len(citation_scores) if citation_scores else 0.0,
        p50_latency_ms=_percentile(latencies, 0.5),
        p95_latency_ms=_percentile(latencies, 0.95),
        n_samples=len(eval_items),
    )


async def _run_agent_config(
    name: str, document_id: str, eval_items: list[EvalItem]
) -> ConfigResult:
    sample = eval_items[:MAX_AGENT_SAMPLES]
    accumulator = RetrievalMetricsAccumulator(k=5)
    latencies: list[float] = []
    faithfulness_scores: list[float] = []
    correctness_scores: list[float] = []
    citation_scores: list[float] = []

    is_council = name == COUNCIL_AGENT_CONFIG
    mode = "agentic" if is_council else name

    for item in sample:
        start = time.perf_counter()
        result = await run_chat_turn(item.question, document_id, mode=mode, council=is_council)
        latencies.append((time.perf_counter() - start) * 1000)

        retrieved_ids = [c["chunk_id"] for c in result["citations"]]
        accumulator.add(retrieved_ids, set(item.source_chunk_ids))

        answer = result["answer"]
        context = "\n\n".join(c["text"] for c in result["citations"]) or "(no citations)"
        faithfulness_scores.append(await score_faithfulness(answer, context))
        correctness_scores.append(
            await score_correctness(answer, item.ground_truth_answer, item.question)
        )
        citation_scores.append(citation_validity(answer, len(result["citations"]) or 1))

    return ConfigResult(
        name=name,
        retrieval_metrics=accumulator.summary(),
        faithfulness=sum(faithfulness_scores) / len(faithfulness_scores)
        if faithfulness_scores
        else 0.0,
        correctness=sum(correctness_scores) / len(correctness_scores)
        if correctness_scores
        else 0.0,
        citation_validity=sum(citation_scores) / len(citation_scores) if citation_scores else 0.0,
        p50_latency_ms=_percentile(latencies, 0.5),
        p95_latency_ms=_percentile(latencies, 0.95),
        n_samples=len(sample),
    )


async def _measure_pii_leak_count(document_id: str) -> int:
    """Scans the real indexed chunk text for raw PII — should always be zero, since masking
    happens before chunking/indexing (Phase 2); this verifies it empirically rather than
    assuming the invariant holds."""
    from sqlalchemy import select

    from app.chunking.models import ChunkRow
    from app.core.db import session_scope

    async with session_scope() as session:
        rows = (
            await session.execute(select(ChunkRow.text).where(ChunkRow.doc_id == document_id))
        ).all()
    return sum(len(detect(text)) for (text,) in rows)


async def run_benchmark(
    document_id: str, eval_items: list[EvalItem], configs: list[str] | None = None
) -> BenchmarkReport:
    from app.guardrails.redteam.runner import run_redteam_suite

    configs = configs or list(ALL_CONFIGS)
    report = BenchmarkReport(document_id=document_id)

    for name in configs:
        if name in RETRIEVAL_CONFIGS:
            report.config_results.append(await _run_retrieval_config(name, document_id, eval_items))
        elif name in AGENT_CONFIGS or name == COUNCIL_AGENT_CONFIG:
            report.config_results.append(await _run_agent_config(name, document_id, eval_items))

    redteam_report = await run_redteam_suite()
    report.injection_block_rate = redteam_report.block_rate
    report.pii_leak_count = await _measure_pii_leak_count(document_id)
    return report
