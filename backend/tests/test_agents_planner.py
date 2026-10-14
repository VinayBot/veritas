from __future__ import annotations

import pytest

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


def test_tool_call_arguments_are_repaired_not_rejected() -> None:
    from app.agents.planner import PlanArgs, _normalise

    args = PlanArgs.model_validate(
        {"category": "pii_lookup", "sub_questions": "[]", "tools": '["pii_vault_lookup"]'}
    )
    assert args.tools == ["pii_vault_lookup"] and args.sub_questions == []
    plan = _normalise(args.category, args.sub_questions, args.tools, "Who is on call?")
    assert plan == {
        "category": "pii_lookup",
        "sub_questions": ["Who is on call?"],
        "tools": ["pii_vault_lookup"],
    }
    # Retrieval always includes hybrid search unless it is a contact lookup.
    assert _normalise("comparison", [], ["graph_traverse"], "q")["tools"] == [
        "hybrid_search",
        "graph_traverse",
    ]


async def test_a_missing_tool_call_falls_back_to_the_json_plan(monkeypatch) -> None:
    from app.agents import planner

    async def no_call(*_a, **_k):
        return None

    async def json_reply(*_a, **_k):
        return '{"category": "factoid", "sub_questions": ["q"], "tools": ["hybrid_search"]}'

    monkeypatch.setattr(planner, "complete_tool_call", no_call)
    monkeypatch.setattr(planner, "complete", json_reply)
    result = await planner.plan("q")
    assert result["via"] == "json" and result["category"] == "factoid"


@pytest.mark.needs_ollama
async def test_the_planner_uses_a_native_tool_call() -> None:
    from app.agents.planner import plan

    result = await plan("Compare the remote work and the travel approval rules.", mode="tool_call")
    assert result["via"] == "tool_call"
    assert result["category"] in ("comparison", "multi_hop")
    assert "hybrid_search" in result["tools"]
