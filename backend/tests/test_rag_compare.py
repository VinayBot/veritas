from __future__ import annotations

import pytest
from conftest import upload_and_wait_ready
from httpx import AsyncClient

from app.core import jobs
from app.rag_engines import compare
from app.rag_engines.compare import compute_deltas, pick_winner

POLICY = (
    b"# Vacation Policy\n\nEmployees accrue two paid vacation days per month of service, up to "
    b"a maximum of twenty-four days per year. Managers must approve requests at least two "
    b"weeks in advance.\n\n# Travel\n\nTrips costing more than five thousand dollars require "
    b"approval from a Vice President.\n"
)


def result(name: str, **overrides: object) -> dict:
    base: dict = {
        "name": name,
        "retrieval_metrics": {"precision_at_5": 0.4, "recall_at_5": 0.6, "ndcg_at_5": 0.5, "n": 12},
        "faithfulness": 0.70,
        "answer_relevancy": 0.80,
        "correctness": 0.60,
        "p50_latency_ms": 4000.0,
        "p95_latency_ms": 6000.0,
        "n_samples": 12,
        "n_judged": {"faithfulness": 12, "relevancy": 12, "correctness": 12},
        "avg_prompt_tokens": 900.0,
        "avg_completion_tokens": 100.0,
        "skipped_reason": None,
    }
    base.update(overrides)
    return base


def test_deltas_are_the_measured_difference_with_their_sample_size() -> None:
    base = result("hybrid_rerank")
    other = result("agentic", faithfulness=0.824, correctness=0.681, p50_latency_ms=5900.0)
    deltas = compute_deltas(base, other)
    assert deltas["faithfulness"]["points"] == 12.4
    assert deltas["correctness"]["points"] == 8.1
    assert deltas["faithfulness"]["n"] == 12 and not deltas["faithfulness"]["small_sample"]
    assert deltas["p50_latency_ms"]["delta"] == 1900.0
    assert deltas["tokens_per_question"]["delta"] == 0.0


def test_no_delta_is_reported_for_a_metric_either_side_did_not_measure() -> None:
    base = result("hybrid_rerank", correctness=None)
    other = result(
        "hyde", faithfulness=None, n_judged={"faithfulness": 0, "relevancy": 12, "correctness": 12}
    )
    deltas = compute_deltas(base, other)
    assert "correctness" not in deltas
    assert "faithfulness" not in deltas
    assert "answer_relevancy" in deltas


def test_small_samples_are_flagged_indicative() -> None:
    base = result(
        "hybrid_rerank", n_samples=5, n_judged={"faithfulness": 5, "relevancy": 5, "correctness": 5}
    )
    other = result(
        "agentic", n_samples=5, n_judged={"faithfulness": 4, "relevancy": 5, "correctness": 5}
    )
    deltas = compute_deltas(base, other)
    assert deltas["faithfulness"]["n"] == 4  # the smaller of the two sides
    assert all(d["small_sample"] for d in deltas.values())


def test_winner_needs_a_real_margin_and_its_reason_quotes_the_deltas() -> None:
    base = result("hybrid_rerank")
    better = result("agentic", faithfulness=0.90, correctness=0.80, p50_latency_ms=9000.0)
    deltas = {"agentic": compute_deltas(base, better)}
    winner = pick_winner([base, better], "hybrid_rerank", deltas)
    assert winner is not None and winner["id"] == "agentic" and not winner["is_baseline"]
    assert "faithfulness +20.0 pts" in winner["reason"]
    assert "latency +5.0s" in winner["reason"]
    assert "12 questions" in winner["reason"]

    tie = result("hybrid", faithfulness=0.705)
    kept = pick_winner([base, tie], "hybrid_rerank", {"hybrid": compute_deltas(base, tie)})
    assert kept is not None and kept["is_baseline"] and "keep the default" in kept["reason"]


def test_no_winner_is_declared_without_measurements() -> None:
    base = result(
        "hybrid_rerank",
        faithfulness=None,
        correctness=None,
        answer_relevancy=None,
        retrieval_metrics={},
    )
    other = result(
        "hyde", faithfulness=None, correctness=None, answer_relevancy=None, retrieval_metrics={}
    )
    assert pick_winner([base, other], "hybrid_rerank", {}) is None


async def test_estimate_states_questions_strategies_and_where_each_latency_came_from(
    client: AsyncClient,
) -> None:
    doc = await upload_and_wait_ready(client, "policy.md", POLICY, "text/markdown")
    resp = await client.post(
        "/api/v1/rag/compare/estimate",
        json={
            "document_id": doc["id"],
            "strategies": ["hybrid", "agentic"],
            "query": "Who approves trips?",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    by_id = {s["strategy"]: s for s in body["strategies"]}
    assert set(by_id) == {"hybrid_rerank", "hybrid", "agentic"}  # the default is always included
    assert all(s["questions"] == 1 and not s["cached"] for s in by_id.values())
    assert all(
        s["latency_source"] == "estimated" or s["latency_source"].startswith("measured over")
        for s in by_id.values()
    )
    assert body["estimated_seconds"] > 0 and body["total_llm_calls"] > 0
    assert not body["all_cached"]


async def test_a_real_single_question_comparison_is_measured_then_served_from_cache(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = await upload_and_wait_ready(client, "policy.md", POLICY, "text/markdown")
    payload = {
        "document_id": doc["id"],
        "strategies": ["hybrid"],
        "query": "How many vacation days do employees accrue per month?",
    }
    started = await client.post("/api/v1/rag/compare", json=payload)
    assert started.status_code == 200
    job = await jobs.wait(started.json()["job_id"], timeout=300)
    assert job.status == "done", job.error

    comparison = (await client.get(f"/api/v1/rag/comparisons/{job.result['comparison_id']}")).json()
    body = comparison["result"]
    assert body["baseline"] == "hybrid_rerank"
    assert [s["name"] for s in body["strategies"]] == ["hybrid_rerank", "hybrid"]
    assert set(body["ran"]) == {"hybrid_rerank", "hybrid"}
    for strategy in body["strategies"]:
        assert strategy["cached"] is False
        assert strategy["samples"][0]["answer"]  # the actual answer each one produced
        assert strategy["p50_latency_ms"] > 0
        assert strategy["correctness"] is None  # no reference answer for a live question
    assert body["n_queries"] == 1 and body["small_sample"] is True
    assert "Indicative, small sample" in body["small_sample_note"]
    for delta in body["deltas"]["hybrid"].values():
        assert delta["small_sample"] and delta["n"] == 1

    # Reopening: the estimate knows it is free, and nothing is executed again.
    estimate = (await client.post("/api/v1/rag/compare/estimate", json=payload)).json()
    assert estimate["all_cached"] and estimate["estimated_seconds"] == 0

    async def must_not_run(*_args: object, **_kwargs: object):
        raise AssertionError("a cached comparison re-ran a strategy")

    monkeypatch.setattr(compare, "answer_question", must_not_run)
    again = await client.post("/api/v1/rag/compare", json=payload)
    rerun = await jobs.wait(again.json()["job_id"], timeout=60)
    assert rerun.status == "done", rerun.error
    cached = (await client.get(f"/api/v1/rag/comparisons/{rerun.result['comparison_id']}")).json()
    assert cached["result"]["ran"] == []
    assert all(s["cached"] for s in cached["result"]["strategies"])

    listing = (await client.get(f"/api/v1/documents/{doc['id']}/comparisons")).json()
    assert len(listing["comparisons"]) == 2


async def test_comparison_needs_exactly_one_of_eval_set_and_question(client: AsyncClient) -> None:
    doc = await upload_and_wait_ready(client, "policy.md", POLICY, "text/markdown")
    resp = await client.post(
        "/api/v1/rag/compare", json={"document_id": doc["id"], "strategies": ["hybrid"]}
    )
    assert resp.status_code == 422 and resp.json()["code"] == "invalid_comparison"
    unknown = await client.post(
        "/api/v1/rag/compare",
        json={"document_id": doc["id"], "strategies": ["bogus"], "query": "x"},
    )
    assert unknown.status_code == 422 and unknown.json()["code"] == "invalid_strategy"
