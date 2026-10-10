"""API-facing glue for the evaluation module: generates+persists a synthetic dataset, and
runs+persists a benchmark (also refreshing docs/BENCHMARKS.md from the same real run — the
file is never hand-edited, see app/evaluation/report.py)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.core.db import session_scope
from app.evaluation.benchmark import BenchmarkReport, run_benchmark
from app.evaluation.datasets import generate_dataset, save_dataset
from app.evaluation.models import BenchmarkRun, EvalDataset
from app.evaluation.report import write_benchmarks_doc


class EvaluationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


async def generate_and_save_dataset(document_id: str, target_size: int) -> EvalDataset:
    items = await generate_dataset(document_id, target_size=target_size)
    if not items:
        raise EvaluationError(
            "dataset_empty",
            f"Could not generate any eval items for {document_id} — the document may have no "
            "indexed chunks yet, or the LLM is unavailable.",
        )
    return await save_dataset(document_id, items)


def _config_result_dict(report: BenchmarkReport, result) -> dict:
    return {
        "name": result.name,
        "retrieval_metrics": result.retrieval_metrics,
        "faithfulness": result.faithfulness,
        "correctness": result.correctness,
        "citation_validity": result.citation_validity,
        "p50_latency_ms": result.p50_latency_ms,
        "p95_latency_ms": result.p95_latency_ms,
        "n_samples": result.n_samples,
        "production_score": report.production_score(result),
        "passes_hard_gates": report.passes_hard_gates(result),
    }


async def run_and_save_benchmark(
    document_id: str, configs: list[str] | None, dataset_target_size: int
) -> tuple[BenchmarkRun, BenchmarkReport]:
    eval_items = await generate_dataset(document_id, target_size=dataset_target_size)
    if not eval_items:
        raise EvaluationError(
            "dataset_empty",
            f"Could not generate any eval items for {document_id} — the document may have no "
            "indexed chunks yet, or the LLM is unavailable.",
        )

    report = await run_benchmark(document_id, eval_items, configs=configs)
    write_benchmarks_doc(report)

    recommended = report.recommended_config()
    row = BenchmarkRun(
        id=str(uuid.uuid4()),
        document_id=document_id,
        config_results=[_config_result_dict(report, r) for r in report.config_results],
        production_recommendation={
            "name": recommended.name if recommended else None,
            "injection_block_rate": report.injection_block_rate,
            "pii_leak_count": report.pii_leak_count,
        },
        created_at=datetime.now(UTC),
    )
    async with session_scope() as session:
        session.add(row)
        await session.commit()
    return row, report


async def get_benchmark_run(run_id: str) -> BenchmarkRun | None:
    async with session_scope() as session:
        return await session.get(BenchmarkRun, run_id)
