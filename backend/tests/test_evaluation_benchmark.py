from __future__ import annotations

import uuid

import pytest
from conftest import wait_for_document
from httpx import AsyncClient

from app.evaluation.benchmark import run_benchmark
from app.evaluation.datasets import EvalItem, generate_dataset
from app.evaluation.report import render_markdown


@pytest.mark.needs_ollama
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

    report = await run_benchmark(document_id, eval_items, configs=["hybrid", "hybrid_rerank"])
    assert len(report.config_results) == 2
    for result in report.config_results:
        assert result.skipped_reason is None
        assert result.n_samples == len(eval_items)
        assert result.p95_latency_ms >= result.p50_latency_ms > 0
        # Every strategy really answered every question; nothing is scored on a stand-in.
        assert len(result.samples) == result.n_samples
        assert all(sample["answer"] for sample in result.samples)
        # A mean exists exactly when at least one sample was judged — never a default.
        for metric, key in (("faithfulness", "faithfulness"), ("correctness", "correctness")):
            value = getattr(result, metric)
            assert (value is None) == (result.n_judged[key] == 0)
            if value is not None:
                assert 0.0 <= value <= 1.0
        assert result.avg_llm_calls is not None and result.avg_llm_calls >= 1

    assert 0.0 <= report.injection_block_rate <= 1.0
    assert report.pii_leak_count == 0  # masking happens before indexing — verified, not assumed

    recommended = report.recommended_config()
    assert recommended is not None
    assert recommended.name in {"hybrid", "hybrid_rerank"}

    markdown = render_markdown(report)
    assert "# Benchmarks" in markdown
    assert document_id in markdown
    assert "hybrid_rerank" in markdown and "| hybrid |" in markdown


@pytest.mark.needs_ollama
async def test_benchmark_runs_the_council_strategy_when_explicitly_requested(
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
    # about the council strategy wiring real council synthesis into the benchmark path, not dataset
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

    report = await run_benchmark(document_id, eval_items, configs=["council"], include_safety=False)
    assert len(report.config_results) == 1
    result = report.config_results[0]
    assert result.name == "council"
    assert result.n_samples == 1
    assert result.samples[0]["answer"]
    assert result.correctness is None or 0.0 <= result.correctness <= 1.0
    # The red-team suite was not part of this run, and the report says so rather than 0.
    assert report.injection_block_rate is None
    assert "red-team suite not run" in report.gate_failures(result)


def test_pick_questions_takes_turns_across_question_types() -> None:
    from app.evaluation.benchmark import pick_questions
    from app.evaluation.datasets import EvalItem

    def item(i: int, category: str) -> EvalItem:
        return EvalItem(
            id=f"q{i}",
            question=f"Q{i}",
            ground_truth_answer="A",
            source_chunk_ids=[],
            category=category,
        )

    items = [item(i, "factoid") for i in range(6)] + [item(10, "comparison"), item(11, "pii")]
    picked = pick_questions(items, 5)
    assert len(picked) == 5
    assert {p.category for p in picked} == {"factoid", "comparison", "pii"}
    assert pick_questions(items, 5) == picked  # deterministic
    assert pick_questions(items[:3], 5) == items[:3]


def test_saying_the_document_lacks_a_stated_answer_is_not_correct():
    from app.evaluation.judge import says_not_covered

    assert says_not_covered("Excerpt 1 does not mention the father of artificial intelligence.")
    assert says_not_covered("Not answerable from this document.")
    assert not says_not_covered("John McCarthy developed LISP in 1958 [1].")


def test_generated_questions_must_not_name_their_excerpts():
    from app.evaluation.datasets import _MENTIONS_EXCERPT_RE

    for leaked in (
        "According to Excerpt 1, who founded it?",
        "What goal is described in both texts?",
        "How do the definitions differ between the two sources?",
        "What does the passage say about NLP?",
    ):
        assert _MENTIONS_EXCERPT_RE.search(leaked)
    assert not _MENTIONS_EXCERPT_RE.search("Who is known as the father of artificial intelligence?")
