from __future__ import annotations

from app.agents.planner import CATEGORIES, _heuristic_fallback, plan


def test_heuristic_fallback_detects_comparison() -> None:
    result = _heuristic_fallback("Compare the vacation policy versus the sick leave policy.")
    assert result["category"] == "comparison"


def test_heuristic_fallback_detects_pii_lookup() -> None:
    result = _heuristic_fallback("What is the email of the HR contact?")
    assert result["category"] == "pii_lookup"
    assert result["tools"] == ["pii_vault_lookup"]


def test_heuristic_fallback_defaults_to_factoid() -> None:
    result = _heuristic_fallback("How many vacation days do employees get?")
    assert result["category"] == "factoid"
    assert result["tools"] == ["hybrid_search"]


async def test_plan_falls_back_cleanly_when_llm_unavailable() -> None:
    result = await plan(
        "How many vacation days do employees get?", model="ollama/does-not-exist:0b"
    )
    assert result["category"] in CATEGORIES
    assert result["sub_questions"]
    assert result["tools"]


async def test_plan_real_llm_call_returns_well_formed_result() -> None:
    result = await plan(
        "How does the vacation policy compare to the sick leave policy?", model="ollama/llama3.2:3b"
    )
    assert result["category"] in CATEGORIES
    assert isinstance(result["sub_questions"], list)
    assert 1 <= len(result["sub_questions"]) <= 4
    assert all(
        t in ("hybrid_search", "graph_traverse", "pii_vault_lookup", "metadata_filter")
        for t in result["tools"]
    )
