#!/usr/bin/env python3
"""`make demo` (Phase 6 backlog item 12: "a first-run demo dataset so Evaluation and the
Knowledge Graph are never empty on a fresh install"). The `data/demo/` assets this target's own
previous stub comment said it was waiting on already exist — this just wires them up: ingests
the bundled Northwind PDF, waits for ingestion AND background enrichment (graph/profile) to
finish so the Knowledge Graph has real entities, then runs a real (fast, 2-config) benchmark and
a real Advisor tournament so the Evaluation page's run history and chunking-strategy table are
populated too. Prints the resulting document_id; it appears in the UI's document switcher,
which lists every ingested document.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, ".")

from app.core.db import init_db  # noqa: E402
from app.evaluation.service import run_and_save_benchmark  # noqa: E402
from app.ingestion.service import get_document, ingest_upload  # noqa: E402
from app.profiler import service as profiler_service  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_DOC = _REPO_ROOT / "data" / "demo" / "northwind_remote_work_travel_policy.pdf"


async def _wait_for(document_id: str, predicate, label: str, timeout: float = 300.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        doc = await get_document(document_id)
        if doc is not None and predicate(doc):
            return
        if doc is not None and doc.status == "failed":
            raise RuntimeError(f"ingestion failed at {doc.error_stage}: {doc.error_message}")
        if asyncio.get_event_loop().time() > deadline:
            print(f"  (timed out waiting for {label} — continuing anyway, best-effort)")
            return
        await asyncio.sleep(1.0)


async def main() -> int:
    await init_db()

    print(f"Ingesting demo document: {_DEMO_DOC.name}")
    document_id = await ingest_upload(_DEMO_DOC.name, _DEMO_DOC.read_bytes(), "application/pdf")
    print(f"Queued as document_id={document_id}")

    print("Waiting for ingestion (chunk/embed/index)...")
    await _wait_for(document_id, lambda d: d.status in ("ready", "cancelled"), "ingestion")

    print(
        "Waiting for background enrichment (graph extraction) so the Knowledge Graph isn't empty..."
    )
    await _wait_for(document_id, lambda d: d.enrichment_status in ("done", "failed"), "enrichment")

    doc = await get_document(document_id)
    if doc is None or doc.status != "ready":
        print("Ingestion did not reach 'ready' — stopping before benchmark/advisor.")
        return 1
    print(
        f"Ready: {doc.chunk_count} chunks, {doc.graph_entity_count} entities, "
        f"{doc.graph_triple_count} relations."
    )

    print("\nRunning a fast real benchmark (hybrid + hybrid_rerank, without the red-team suite)")
    print("to seed Evaluation's run history...")
    _run, report = await run_and_save_benchmark(
        document_id,
        configs=["hybrid", "hybrid_rerank"],
        dataset_target_size=6,
        include_safety=False,
    )
    recommended = report.recommended_config()
    print(f"Benchmark done — recommended: {recommended.name if recommended else 'none'}")

    print("\nRunning the real Advisor tournament (all 6 chunking strategies)")
    print("to seed the chunking-strategy table...")
    assert doc.masked_text is not None
    doc_profile = await profiler_service.profile(
        document_id, doc.masked_text, doc.language, doc.ocr_confidence
    )
    recommendation = await profiler_service.run_advisor(
        document_id, doc.masked_text, doc_profile, dataset_target_size=6
    )
    if recommendation is not None:
        print(f"Advisor done — suggested: {recommendation.suggested.config.chunking_strategy}")
    else:
        print("Advisor had nothing to recommend (document too small) —")
        print("Evaluation's table will stay empty for this doc.")

    print(f"\nDone. document_id={document_id}")
    print("Open the app and pick this document from the document switcher in the sidebar.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
