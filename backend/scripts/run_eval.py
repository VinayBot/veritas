#!/usr/bin/env python3
"""`make eval`. Ingests the bundled demo document (or one given on the command line), runs the
real multi-config benchmark against it (app/evaluation/benchmark.py), writes docs/BENCHMARKS.md
from that same real run, and exits non-zero if no config clears the hard gates (Section 11:
faithfulness >= 0.85, injection block rate >= 95%, zero PII leaks, p95 latency <= 15s) — the
same "at least one shippable config" bar run_redteam.py applies to the guardrail suite.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.core.db import init_db  # noqa: E402
from app.evaluation.benchmark import BenchmarkReport  # noqa: E402
from app.evaluation.service import run_and_save_benchmark  # noqa: E402
from app.ingestion.service import get_document, ingest_upload  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DEMO_DOC = _REPO_ROOT / "data" / "demo" / "hr_handbook.md"


async def _wait_until_ready(document_id: str, timeout: float = 300.0) -> None:
    """ingest_upload() now queues a detached background job and returns almost immediately
    (see app/ingestion/service.py) instead of blocking until the document is fully processed —
    this script needs the chunks/index to exist before it can run a benchmark against them."""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        doc = await get_document(document_id)
        if doc is not None and doc.status in ("ready", "failed", "cancelled"):
            if doc.status != "ready":
                raise RuntimeError(
                    f"ingestion did not become ready (status={doc.status}, "
                    f"stage={doc.error_stage}): {doc.error_message}"
                )
            return
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError(f"document {document_id} did not become ready within {timeout}s")
        await asyncio.sleep(0.5)


def _print_report(report: BenchmarkReport) -> None:
    header = (
        f"{'Config':<20} {'nDCG@5':>8} {'Faithful':>9} {'Correct':>8} "
        f"{'p95(ms)':>9} {'Score':>7} Gate"
    )
    print(header)
    for result in report.config_results:
        score = report.production_score(result)
        gate = "PASS" if report.passes_hard_gates(result) else "fail"
        ndcg = result.retrieval_metrics.get("ndcg_at_5", 0.0)
        line = (
            f"{result.name:<20} {ndcg:>8.3f} {result.faithfulness:>9.3f} "
            f"{result.correctness:>8.3f} {result.p95_latency_ms:>9.0f} {score:>7.3f} {gate}"
        )
        print(line)
    print()
    print(
        f"Safety: injection block rate {report.injection_block_rate:.1%}, "
        f"PII leak count {report.pii_leak_count}"
    )


async def main() -> int:
    await init_db()

    doc_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if doc_arg and doc_arg.strip():
        document_id = doc_arg.strip()
        print(f"Using existing document_id={document_id}")
    else:
        demo_path = _DEFAULT_DEMO_DOC
        print(f"Ingesting demo document: {demo_path}")
        document_id = await ingest_upload(demo_path.name, demo_path.read_bytes(), "text/markdown")
        print(f"Queued as document_id={document_id}, waiting for ingestion to finish...")
        await _wait_until_ready(document_id)
        print("Ingestion ready.")

    print("Running benchmark (dataset generation + all retrieval/agent configs + red-team)...")
    _run, report = await run_and_save_benchmark(document_id, configs=None, dataset_target_size=10)

    print()
    _print_report(report)

    recommended = report.recommended_config()
    passed = recommended is not None and report.passes_hard_gates(recommended)
    print()
    if recommended is not None and passed:
        print(f"PASS — '{recommended.name}' clears every hard gate. docs/BENCHMARKS.md updated.")
    else:
        print("FAIL — no config cleared every hard gate. See docs/BENCHMARKS.md for details.")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
