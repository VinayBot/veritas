"""Per-query model routing: picks a model based on real, measured properties of the query
text (length, comparison/multi-part phrasing) rather than always using the same default —
longer or multi-part questions get the strongest locally-available model, short single-fact
questions stay on the fast default so they're not paying a bigger model's latency for nothing.

Independent of (and runs before) the agentic Planner's own LLM-based category classification:
the Planner decides *retrieval* strategy for the agentic graph specifically, this decides which
model answers in *every* mode, with no extra LLM call of its own.

Separately, every routed call carries a latency budget (`MODEL_ROUTER_LATENCY_BUDGET_MS`): if
the chosen model doesn't respond within it, this falls back to `DEFAULT_LLM_MODEL` (the fast
one) with a full-length timeout, so a slow/stuck model never blocks an answer indefinitely. The
fallback is a real second `complete()` call made only when the first one actually raises
`LlmUnavailableError` — not a simulated/pre-decided outcome.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.config import get_settings
from app.llm.client import LlmUnavailableError, complete

SIMPLE_QUERY_MAX_WORDS = 12
_COMPLEXITY_KEYWORDS = (
    "compare",
    "comparison",
    "difference",
    "versus",
    " vs ",
    "why",
    "relationship",
    "both",
    "between",
)


@dataclass
class RoutedCompletion:
    answer: str
    primary_model: str
    model_used: str
    fell_back: bool
    latency_ms: float


def select_primary_model(query: str) -> str:
    settings = get_settings()
    lowered = query.lower()
    is_complex = (
        len(query.split()) > SIMPLE_QUERY_MAX_WORDS
        or query.count("?") > 1
        or any(kw in lowered for kw in _COMPLEXITY_KEYWORDS)
    )
    if not is_complex:
        return settings.default_llm_model

    stronger = [m for m in settings.council_model_list if m != settings.default_llm_model]
    return stronger[0] if stronger else settings.default_llm_model


async def complete_with_latency_budget(
    prompt: str,
    *,
    query_for_routing: str,
    system: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0.2,
) -> RoutedCompletion:
    settings = get_settings()
    primary_model = select_primary_model(query_for_routing)
    fallback_model = settings.default_llm_model
    budget_s = settings.model_router_latency_budget_ms / 1000

    start = time.perf_counter()
    try:
        answer = await complete(
            prompt,
            model=primary_model,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=budget_s,
        )
        return RoutedCompletion(
            answer=answer,
            primary_model=primary_model,
            model_used=primary_model,
            fell_back=False,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
    except LlmUnavailableError:
        pass  # fall through to the backup model below — a real retry, not a canned outcome

    if fallback_model == primary_model:
        raise LlmUnavailableError(f"{primary_model} unavailable and is already the fallback")

    answer = await complete(
        prompt,
        model=fallback_model,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return RoutedCompletion(
        answer=answer,
        primary_model=primary_model,
        model_used=fallback_model,
        fell_back=True,
        latency_ms=(time.perf_counter() - start) * 1000,
    )
