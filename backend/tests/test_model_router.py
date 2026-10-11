from __future__ import annotations

import pytest

from app.core.config import get_settings
from app.llm.client import LlmUnavailableError
from app.llm.router import complete_with_latency_budget, select_primary_model


def test_select_primary_model_uses_fast_default_for_short_simple_queries() -> None:
    settings = get_settings()
    assert select_primary_model("What is the vacation policy?") == settings.default_llm_model


def test_select_primary_model_uses_a_stronger_model_for_comparison_queries() -> None:
    settings = get_settings()
    stronger = select_primary_model(
        "What's the difference between the vacation policy and the remote work policy?"
    )
    assert stronger != settings.default_llm_model
    assert stronger in settings.council_model_list


def test_select_primary_model_uses_a_stronger_model_for_long_queries() -> None:
    settings = get_settings()
    long_query = (
        "I would like to understand in detail how vacation accrual works for part-time "
        "employees who also take occasional unpaid leave during the calendar year"
    )
    assert len(long_query.split()) > 12
    assert select_primary_model(long_query) != settings.default_llm_model


async def test_complete_with_latency_budget_uses_primary_when_it_succeeds() -> None:
    result = await complete_with_latency_budget(
        "Reply with the single word: hello", query_for_routing="hi", max_tokens=10
    )
    assert result.fell_back is False
    assert result.model_used == result.primary_model
    assert result.answer
    assert result.latency_ms > 0


async def test_complete_with_latency_budget_force_primary_model_overrides_the_pick() -> None:
    settings = get_settings()
    simple_query = "What is the vacation policy?"
    assert select_primary_model(simple_query) == settings.default_llm_model

    forced = settings.council_model_list[0]
    result = await complete_with_latency_budget(
        "Reply with the single word: hello",
        query_for_routing=simple_query,
        max_tokens=10,
        force_primary_model=forced,
    )
    assert result.primary_model == forced
    assert result.fell_back is False
    assert result.model_used == forced


async def test_complete_with_latency_budget_falls_back_when_primary_is_unavailable(
    monkeypatch,
) -> None:
    settings = get_settings()
    bogus_model = "ollama/this-model-does-not-exist:1b"
    monkeypatch.setattr(settings, "council_models", bogus_model)

    complex_query = (
        "Compare the vacation policy and the remote work policy — what's the difference "
        "between them?"
    )
    assert select_primary_model(complex_query) == bogus_model

    result = await complete_with_latency_budget(
        "Answer briefly.", query_for_routing=complex_query, max_tokens=20
    )
    assert result.primary_model == bogus_model
    assert result.fell_back is True
    assert result.model_used == settings.default_llm_model
    assert result.answer


async def test_complete_with_latency_budget_falls_back_when_primary_exceeds_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other fallback test above forces an immediate connection error (a bogus model name)
    — that exercises LlmUnavailableError's exception-handling branch but never the
    *timeout* branch itself (primary model slow-but-eventually-responding, exceeding
    budget_s). A real Ollama call against a 1ms budget reliably exceeds it, no mocking needed.
    Needs a *complex* query, not a simple one: a simple query routes primary == fallback ==
    default_llm_model, which is the other (raise, no distinct fallback to try) branch — this
    one specifically needs primary and fallback to differ, so a real fallback happens."""
    settings = get_settings()
    monkeypatch.setattr(settings, "model_router_latency_budget_ms", 1)
    complex_query = (
        "Compare the vacation policy and the remote work policy — what's the difference "
        "between them?"
    )
    primary = select_primary_model(complex_query)
    assert primary != settings.default_llm_model

    result = await complete_with_latency_budget(
        "Reply with the single word: hello", query_for_routing=complex_query, max_tokens=10
    )
    assert result.primary_model == primary
    assert result.fell_back is True
    assert result.model_used == settings.default_llm_model
    assert result.answer


async def test_complete_with_latency_budget_raises_when_fallback_equals_the_failed_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    bogus_model = "ollama/this-model-does-not-exist:1b"
    monkeypatch.setattr(settings, "default_llm_model", bogus_model)
    simple_query = "What is the vacation policy?"
    assert select_primary_model(simple_query) == bogus_model

    with pytest.raises(LlmUnavailableError):
        await complete_with_latency_budget(
            "Answer briefly.", query_for_routing=simple_query, max_tokens=20
        )
