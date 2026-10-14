"""RAG strategies end to end against real retrieval and a real local model."""

from __future__ import annotations

import json
import uuid

import pytest
from conftest import upload_and_wait_ready, wait_for_enrichment
from httpx import AsyncClient

from app.core import jobs, runtime_settings
from app.rag_engines import availability
from app.rag_engines.registry import (
    FALLBACK_DEFAULT,
    STRATEGIES,
    default_strategy_id,
    get_strategy,
    strategy_for_report,
)
from app.rag_engines.variants import has_variant

POLICY = (
    b"# Vacation Policy\n\nEmployees accrue two paid vacation days per month of service, up to "
    b"a maximum of twenty-four days per year. Managers must approve requests at least two "
    b"weeks in advance.\n\n# Remote Work\n\nAfter a ninety-day probation, employees may work "
    b"remotely three days per week. Contractors need written approval from their manager.\n\n"
    b"# Travel\n\nTrips costing more than five thousand dollars require approval from a Vice "
    b"President. Economy class is required for flights under six hours.\n"
)


def _events(text: str) -> list[tuple[str, str]]:
    out = []
    for block in text.strip().split("\n\n"):
        if block.strip():
            event_line, data_line = block.split("\n", 1)
            out.append((event_line.removeprefix("event: "), data_line.removeprefix("data: ")))
    return out


async def _ask(client: AsyncClient, document_id: str, question: str, **extra: object) -> dict:
    resp = await client.post(
        "/api/v1/chat", json={"message": question, "document_id": document_id, **extra}
    )
    events = _events(resp.text)
    names = [e for e, _ in events]
    assert "error" not in names, events
    done = json.loads(next(d for e, d in events if e == "done"))
    report = (await client.get(f"/api/v1/reports/{done['report_id']}")).json()
    return {"events": events, "names": names, "report": report}


@pytest.fixture(autouse=True)
async def _restore_default():
    yield
    await runtime_settings.set_value("default_strategy", None)


def test_registry_has_the_eight_strategies_with_complete_declarations() -> None:
    assert list(STRATEGIES) == [
        "naive",
        "hybrid",
        "hybrid_rerank",
        "hyde",
        "semantic_chunk",
        "graph_rag",
        "agentic",
        "council",
    ]
    for spec in STRATEGIES.values():
        assert spec.display_name and spec.description and spec.best_for
        assert spec.components and spec.suited_for
        assert spec.typical_latency_ms > 0
        assert spec.relative_cost in {"low", "medium", "high", "very_high"}
        assert spec.min_hardware_tier in {"8gb", "16gb"}
        assert (spec.plan is None) == (spec.kind == "agentic")
    assert get_strategy("naive").plan.variant == "fixed_512"
    assert get_strategy("naive").plan.mode == "dense"
    assert get_strategy("hyde").plan.hyde and get_strategy("graph_rag").plan.graph
    assert get_strategy("council").council


def test_reports_written_before_strategies_map_to_what_they_actually_ran() -> None:
    assert strategy_for_report(None, "hybrid") == "hybrid_rerank"  # old "hybrid" reranked
    assert strategy_for_report(None, "graph") == "graph_rag"
    assert strategy_for_report(None, "agentic") == "agentic"
    assert strategy_for_report("hybrid", "hybrid") == "hybrid"  # new rows say exactly


async def test_strategies_endpoint_reports_live_availability_per_document(
    client: AsyncClient,
) -> None:
    doc = await upload_and_wait_ready(client, "policy.md", POLICY, "text/markdown")
    resp = await client.get("/api/v1/rag/strategies", params={"document_id": doc["id"]})
    assert resp.status_code == 200
    body = resp.json()
    by_id = {s["id"]: s for s in body["strategies"]}
    assert len(by_id) >= 8
    assert body["default"] == FALLBACK_DEFAULT
    assert by_id[FALLBACK_DEFAULT]["is_default"]
    assert by_id["hybrid"]["available"] and by_id["hybrid_rerank"]["available"]
    # Nothing has built the alternative indexes yet: unavailable, with the reason and the fix.
    for needs_index in ("naive", "semantic_chunk"):
        assert by_id[needs_index]["available"] is False
        assert by_id[needs_index]["action"] == "build_index"
        assert "index" in by_id[needs_index]["unavailable_reason"]


async def test_an_unreachable_model_makes_every_strategy_unavailable_with_the_command(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down() -> availability.LlmState:
        return availability.LlmState(
            False, "Ollama is not running. Start it with `ollama serve`", None
        )

    monkeypatch.setattr(availability, "llm_state", down)
    body = (await client.get("/api/v1/rag/strategies")).json()
    assert all(not s["available"] for s in body["strategies"])
    assert all("ollama serve" in s["unavailable_reason"] for s in body["strategies"])


async def test_switching_the_default_is_instant_and_applies_to_the_next_question(
    client: AsyncClient,
) -> None:
    doc = await upload_and_wait_ready(client, "policy.md", POLICY, "text/markdown")
    resp = await client.put("/api/v1/rag/default", json={"strategy": "hybrid"})
    assert resp.status_code == 200 and resp.json()["default"] == "hybrid"
    assert default_strategy_id() == "hybrid"

    # No strategy in the request: the workspace default is used, with no restart or re-ingest.
    asked = await _ask(client, doc["id"], "How many vacation days accrue per month?")
    assert asked["report"]["strategy"] == "hybrid"
    session = json.loads(next(d for e, d in asked["events"] if e == "session"))
    assert session["strategy"] == "hybrid"

    bad = await client.put("/api/v1/rag/default", json={"strategy": "nope"})
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_strategy"


async def test_per_question_strategy_overrides_the_default_and_is_recorded(
    client: AsyncClient,
) -> None:
    doc = await upload_and_wait_ready(client, "policy.md", POLICY, "text/markdown")
    questions = {
        "hybrid": "Who has to approve a trip that costs more than five thousand dollars?",
        "hybrid_rerank": "How many days per week can employees work remotely after probation?",
        "hyde": "What is the yearly maximum number of vacation days?",
    }
    for strategy, question in questions.items():
        asked = await _ask(client, doc["id"], question, strategy=strategy)
        report = asked["report"]
        assert report["strategy"] == strategy
        assert report["answer"]
        assert report["latency_ms"] > 0
        assert report["usage"]["llm_calls"] >= 1
        assert report["usage"]["prompt_tokens"] > 0  # real counts from the provider
        funnel = report["retrieval"]["funnel"]
        assert funnel["in_context"] == len(report["retrieval"]["chunks"]) > 0
        assert funnel["used_in_answer"] == sum(c["used"] for c in report["retrieval"]["chunks"])
        for chunk in report["retrieval"]["chunks"]:
            assert chunk["found_by"] in {"dense", "sparse", "both"}
            assert chunk["page"] is None  # not recorded by any parser yet — never invented
        assert {t["stage"] for t in report["timings"]} >= {
            "guardian_in",
            "retriever",
            "synthesizer",
        }
        assert all(t["duration_ms"] is not None for t in report["timings"])
    # Reranking only happens in strategies that declare it.
    assert funnel["after_rerank"] is not None


async def test_the_answer_is_streamed_before_it_is_scored(client: AsyncClient) -> None:
    doc = await upload_and_wait_ready(client, "policy.md", POLICY, "text/markdown")
    asked = await _ask(client, doc["id"], "How far ahead must vacation be approved?")
    names = asked["names"]
    assert names.index("answer") < names.index("quality") < names.index("done")
    assert max(i for i, n in enumerate(names) if n == "token") < names.index("answer")
    summary = json.loads(next(d for e, d in asked["events"] if e == "answer"))
    assert summary["strategy"] == asked["report"]["strategy"]
    assert summary["latency_ms"] > 0


async def test_normal_questions_get_a_quick_answer_and_deep_ones_a_longer_answer(
    client: AsyncClient,
) -> None:
    doc = await upload_and_wait_ready(client, "policy.md", POLICY, "text/markdown")
    quick = await _ask(client, doc["id"], "What are the remote work rules?")
    deep = await _ask(client, doc["id"], "Explain the remote work rules in detail.")
    assert quick["report"]["detail"] == "brief"
    assert deep["report"]["detail"] == "deep"
    quick_words = len(quick["report"]["answer"].split())
    assert quick_words <= 110, quick["report"]["answer"]
    # The explicit control wins over the phrasing.
    forced = await _ask(client, doc["id"], "Explain the travel rules in detail.", detail="brief")
    assert forced["report"]["detail"] == "brief"

    bad = await client.post(
        "/api/v1/chat", json={"message": "x", "document_id": doc["id"], "detail": "epic"}
    )
    assert _events(bad.text)[0][0] == "error"


async def test_a_strategy_that_needs_an_index_builds_it_with_real_progress_then_runs(
    client: AsyncClient,
) -> None:
    doc = await upload_and_wait_ready(client, "policy.md", POLICY, "text/markdown")
    assert not await has_variant(doc["id"], "fixed_512")

    started = await client.post(
        "/api/v1/rag/strategies/naive/prepare", json={"document_id": doc["id"]}
    )
    assert started.status_code == 200
    job = await jobs.wait(started.json()["job_id"], timeout=180)
    assert job.status == "done", job.error
    assert job.result["action"] == "build_index" and job.result["chunks"] > 0
    assert await has_variant(doc["id"], "fixed_512")

    by_id = {
        s["id"]: s
        for s in (
            await client.get("/api/v1/rag/strategies", params={"document_id": doc["id"]})
        ).json()["strategies"]
    }
    assert by_id["naive"]["available"] and by_id["naive"]["action"] is None

    asked = await _ask(client, doc["id"], "How many vacation days per month?", strategy="naive")
    chunks = asked["report"]["retrieval"]["chunks"]
    assert chunks and all(c["chunking"] == "fixed" for c in chunks)
    assert all(c["found_by"] == "dense" for c in chunks)
    # The working index is untouched by building a variant.
    after = (await client.get(f"/api/v1/documents/{doc['id']}")).json()
    assert after["chunk_count"] == doc["chunk_count"]
    assert after["chunk_strategy"] == doc["chunk_strategy"]

    again = await client.post(
        "/api/v1/rag/strategies/naive/prepare", json={"document_id": doc["id"]}
    )
    assert again.status_code == 409


async def test_recommendation_after_ingest_has_document_derived_reasons(
    client: AsyncClient,
) -> None:
    doc = await upload_and_wait_ready(client, "policy.md", POLICY, "text/markdown")
    await wait_for_enrichment(client, doc["id"])
    resp = await client.get(f"/api/v1/documents/{doc['id']}/recommendation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["recommended"] in STRATEGIES
    assert body["display_name"] == STRATEGIES[body["recommended"]].display_name
    assert 0.5 <= body["confidence"] <= 0.95
    assert body["reasons"] and all(isinstance(r, str) and r for r in body["reasons"])
    assert body["runner_up"] in STRATEGIES
    assert body["features"]["tokens"] > 0
    assert body["rule_trace"]
    # Each reason quotes something measured from this document, not a generic sentence.
    assert all(any(ch.isdigit() for ch in r) for r in body["reasons"])
    fired = [r for r in body["rule_trace"] if r["fired"]]
    assert fired, "a short, sectioned document must trip at least one rule"
    assert body == (await client.get(f"/api/v1/documents/{doc['id']}/recommendation")).json()

    missing = await client.get("/api/v1/documents/nope/recommendation")
    assert missing.status_code == 404


def _measured(name: str, quality: float) -> dict:
    """A strategy result as a comparison stores it; `quality` sets every scored metric."""
    return {
        "name": name,
        "retrieval_metrics": {"ndcg_at_5": quality, "recall_at_5": quality, "n": 5},
        "faithfulness": quality,
        "answer_relevancy": quality,
        "correctness": quality,
        "p50_latency_ms": 1000.0,
        "p95_latency_ms": 1500.0,
        "n_samples": 5,
        "n_judged": {"faithfulness": 5, "relevancy": 5, "correctness": 5},
    }


async def _store_comparison(document_id: str, results: list[dict]) -> None:
    import uuid
    from datetime import UTC, datetime

    from app.core.db import session_scope
    from app.evaluation.models import ComparisonRun

    async with session_scope() as session:
        session.add(
            ComparisonRun(
                id=str(uuid.uuid4()),
                document_id=document_id,
                dataset_id="set-1",
                query=None,
                strategies=[r["name"] for r in results],
                baseline=results[0]["name"],
                result={"strategies": results, "n_queries": 5},
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def test_measured_results_overrule_the_rules_prediction(client: AsyncClient) -> None:
    """Reported by the owner: the card recommended GraphRAG while a comparison on the same
    document showed Hybrid winning. The rules' pick is a prediction; once it has been
    measured and lost, the measured winner is recommended and the card says why."""
    unique = POLICY + f"\n\nRevision {uuid.uuid4()}.".encode()
    doc = await upload_and_wait_ready(client, "policy-a.md", unique, "text/markdown")
    # The rules read the graph, which is built in the background: wait so they stay put.
    await wait_for_enrichment(client, doc["id"])
    before = (await client.get(f"/api/v1/documents/{doc['id']}/recommendation")).json()
    assert before["basis"] == "rules" and before["measured"] is None
    predicted = before["rule_recommended"]

    other = "hybrid" if predicted != "hybrid" else "hybrid_rerank"
    await _store_comparison(doc["id"], [_measured(predicted, 0.55), _measured(other, 0.9)])
    after = (await client.get(f"/api/v1/documents/{doc['id']}/recommendation")).json()
    assert after["basis"] == "measured"
    assert after["recommended"] == other
    assert after["rule_recommended"] == predicted
    assert [e["strategy"] for e in after["measured"]["ranking"]] == [other, predicted]
    assert any("Measured on 5 questions" in r for r in after["reasons"])


async def test_the_measured_best_wins_even_when_the_prediction_was_not_measured(
    client: AsyncClient,
) -> None:
    """The highest measured score decides. A prediction that was never measured is mentioned
    as something to compare, not recommended over a measured result."""
    unique = POLICY + f"\n\nRevision {uuid.uuid4()}.".encode()
    doc = await upload_and_wait_ready(client, "policy-b.md", unique, "text/markdown")
    # The rules read the graph, which is built in the background: wait so they stay put.
    await wait_for_enrichment(client, doc["id"])
    predicted = (await client.get(f"/api/v1/documents/{doc['id']}/recommendation")).json()[
        "rule_recommended"
    ]
    others = [s for s in ("hybrid", "hybrid_rerank", "naive") if s != predicted][:2]
    await _store_comparison(doc["id"], [_measured(others[0], 0.6), _measured(others[1], 0.8)])
    body = (await client.get(f"/api/v1/documents/{doc['id']}/recommendation")).json()
    assert body["basis"] == "measured"
    assert body["recommended"] == others[1]
    assert body["rule_recommended"] == predicted
    assert any("not been measured here" in r for r in body["reasons"])
