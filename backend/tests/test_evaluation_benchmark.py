from __future__ import annotations

import uuid

from conftest import wait_for_document
from httpx import AsyncClient

from app.evaluation.benchmark import run_benchmark
from app.evaluation.datasets import EvalItem, generate_dataset
from app.evaluation.report import render_markdown


async def test_benchmark_runs_real_configs_and_scores_them(client: AsyncClient) -> None:
    content = (
        b"# Vacation Policy\n\n"
        b"Employees accrue two paid vacation days per month of service, up to twenty-four "
        b"days per year. Managers must approve requests at least two weeks in advance.\n"
    )
    files = {"file": ("policy.md", content, "text/markdown")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]
    await wait_for_document(client, document_id)

    eval_items = await generate_dataset(document_id, target_size=5)
    assert eval_items

    report = await run_benchmark(document_id, eval_items, configs=["bm25", "hybrid"])
    assert len(report.config_results) == 2
    for result in report.config_results:
        assert result.n_samples > 0
        assert 0.0 <= result.faithfulness <= 1.0
        assert result.p95_latency_ms >= result.p50_latency_ms

    assert 0.0 <= report.injection_block_rate <= 1.0
    assert report.pii_leak_count == 0  # masking happens before indexing — verified, not assumed

    recommended = report.recommended_config()
    assert recommended is not None
    assert recommended.name in {"bm25", "hybrid"}

    markdown = render_markdown(report)
    assert "# Benchmarks" in markdown
    assert document_id in markdown
    assert "bm25" in markdown and "hybrid" in markdown


async def test_benchmark_runs_agentic_council_when_explicitly_requested(
    client: AsyncClient,
) -> None:
    content = (
        b"# Vacation Policy\n\n"
        b"Employees accrue two paid vacation days per month of service, up to twenty-four "
        b"days per year.\n"
    )
    files = {"file": ("policy.md", content, "text/markdown")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]
    await wait_for_document(client, document_id)

    # One hand-built item (skips generate_dataset's own LLM cost) — this test is specifically
    # about agentic_council wiring real council synthesis into the benchmark path, not dataset
    # generation, which test_benchmark_runs_real_configs_and_scores_them already covers.
    eval_items = [
        EvalItem(
            id=str(uuid.uuid4()),
            category="factoid",
            question="How many vacation days do employees accrue per month?",
            ground_truth_answer="Two paid vacation days per month.",
            source_chunk_ids=[],
        )
    ]

    report = await run_benchmark(document_id, eval_items, configs=["agentic_council"])
    assert len(report.config_results) == 1
    result = report.config_results[0]
    assert result.name == "agentic_council"
    assert result.n_samples == 1
    assert 0.0 <= result.faithfulness <= 1.0
    assert 0.0 <= result.correctness <= 1.0
