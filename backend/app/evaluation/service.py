"""API-facing glue for evaluation: eval sets, benchmark runs, and their persistence.

A run is always tied to a saved eval set. That is what makes two runs comparable: a delta
between runs is only meaningful when both answered the same questions.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.db import session_scope
from app.evaluation.benchmark import (
    HARNESS_VERSION,
    BenchmarkReport,
    Checkpoint,
    Progress,
    _noop_progress,
    run_benchmark,
)
from app.evaluation.datasets import EvalItem, generate_dataset, load_dataset, save_dataset
from app.evaluation.models import BenchmarkRun, EvalDataset
from app.evaluation.report import write_benchmarks_doc
from app.ingestion.models import Document
from app.llm.models_config import get_model_config


class EvaluationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


_EMPTY = (
    "Could not generate any eval items for {document_id} — the document may have no indexed "
    "chunks yet, or the LLM is unavailable."
)


async def generate_and_save_dataset(document_id: str, target_size: int) -> EvalDataset:
    items = await generate_dataset(document_id, target_size=target_size)
    if not items:
        raise EvaluationError("dataset_empty", _EMPTY.format(document_id=document_id))
    return await save_dataset(document_id, items)


async def list_datasets(document_id: str) -> list[EvalDataset]:
    async with session_scope() as session:
        rows = await session.execute(
            select(EvalDataset)
            .where(EvalDataset.document_id == document_id)
            .order_by(EvalDataset.version.desc())
        )
        return list(rows.scalars().all())


async def get_dataset(dataset_id: str) -> EvalDataset | None:
    async with session_scope() as session:
        return await session.get(EvalDataset, dataset_id)


async def resolve_dataset(
    document_id: str, dataset_id: str | None, target_size: int
) -> tuple[EvalDataset, list[EvalItem]]:
    """The eval set a run will use: the one named, else the document's latest, else a new
    one generated now and saved so later runs can reuse it."""
    dataset: EvalDataset | None
    if dataset_id is not None:
        dataset = await get_dataset(dataset_id)
        if dataset is None or dataset.document_id != document_id:
            raise EvaluationError(
                "dataset_not_found", f"No eval set {dataset_id} for document {document_id}"
            )
    else:
        existing = await list_datasets(document_id)
        dataset = existing[0] if existing else None
    if dataset is None:
        dataset = await generate_and_save_dataset(document_id, target_size)
    items = load_dataset(dataset.path)
    if not items:
        raise EvaluationError("dataset_empty", f"Eval set {dataset.id} has no questions.")
    return dataset, items


async def current_run_config(document_id: str) -> dict[str, Any]:
    """What produced the numbers: models and the document's chunking at run time."""
    config = get_model_config()
    async with session_scope() as session:
        doc = await session.get(Document, document_id)
    return {
        "judge": config.judge,
        "generator": config.generator,
        "embedding": config.embedding,
        "reranker": config.reranker,
        "chunking": doc.chunk_strategy if doc else None,
    }


def config_result_dict(report: BenchmarkReport, result) -> dict:
    return {
        **result.to_dict(),
        "production_score": report.production_score(result),
        "passes_hard_gates": report.passes_hard_gates(result),
        "gate_failures": report.gate_failures(result),
    }


async def run_and_save_benchmark(
    document_id: str,
    configs: list[str] | None,
    dataset_target_size: int = 10,
    *,
    dataset_id: str | None = None,
    include_safety: bool = True,
    write_doc: bool = False,
    progress: Progress = _noop_progress,
    checkpoint: Checkpoint | None = None,
    max_questions: int | None = None,
    max_agent_questions: int | None = None,
) -> tuple[BenchmarkRun, BenchmarkReport]:
    """`write_doc` rewrites docs/BENCHMARKS.md from this run. Only `make eval` asks for that;
    a run started from the UI never touches a tracked file."""
    await progress(0.0, "Preparing the eval set")
    dataset, eval_items = await resolve_dataset(document_id, dataset_id, dataset_target_size)

    started = time.perf_counter()
    report = await run_benchmark(
        document_id,
        eval_items,
        configs=configs,
        include_safety=include_safety,
        progress=progress,
        checkpoint=checkpoint,
        max_questions=max_questions,
        max_agent_questions=max_agent_questions,
    )
    if write_doc:
        write_benchmarks_doc(report)

    recommended = report.recommended_config()
    row = BenchmarkRun(
        id=str(uuid.uuid4()),
        document_id=document_id,
        config_results=[config_result_dict(report, r) for r in report.config_results],
        production_recommendation={
            "name": recommended.name if recommended else None,
            "injection_block_rate": report.injection_block_rate,
            "pii_leak_count": report.pii_leak_count,
        },
        created_at=datetime.now(UTC),
        harness_version=HARNESS_VERSION,
        dataset_id=dataset.id,
        dataset_version=dataset.version,
        n_items=len(eval_items),
        run_config=await current_run_config(document_id),
        duration_ms=(time.perf_counter() - started) * 1000,
    )
    async with session_scope() as session:
        session.add(row)
        await session.commit()
    return row, report


async def get_benchmark_run(run_id: str) -> BenchmarkRun | None:
    async with session_scope() as session:
        return await session.get(BenchmarkRun, run_id)


async def list_benchmark_runs(
    document_id: str | None = None, limit: int = 30
) -> list[BenchmarkRun]:
    """Oldest first within the newest `limit` runs, for one document or across all of them."""
    async with session_scope() as session:
        query = select(BenchmarkRun).order_by(BenchmarkRun.created_at.desc()).limit(limit)
        if document_id:
            query = query.where(BenchmarkRun.document_id == document_id)
        rows = list((await session.execute(query)).scalars().all())
    return list(reversed(rows))
