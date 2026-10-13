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
from app.llm.client import LlmUnavailableError, complete, stream_complete
from app.llm.models_config import get_model_config

SIMPLE_QUERY_MAX_WORDS = 12
FALLBACK_TIMEOUT_SECONDS = 60.0
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
    config = get_model_config()
    lowered = query.lower()
    is_complex = (
        len(query.split()) > SIMPLE_QUERY_MAX_WORDS
        or query.count("?") > 1
        or any(kw in lowered for kw in _COMPLEXITY_KEYWORDS)
    )
    if not is_complex:
        return config.generator
    return config.stronger_model() or config.generator


async def complete_with_latency_budget(
    prompt: str,
    *,
    query_for_routing: str,
    system: str | None = None,
    max_tokens: int = 500,
    temperature: float = 0.2,
    force_primary_model: str | None = None,
    stream: bool = False,
) -> RoutedCompletion:
    """`force_primary_model` skips the complexity-based pick below for a call that's always
    reasoning-sensitive regardless of how simple the original query looks — e.g. the
    Synthesizer's revision pass (see docs/TROUBLESHOOTING.md): correcting a flawed answer while
    preserving its citation is a harder task than the first-pass synthesis that `query` alone
    would route as "simple"."""
    settings = get_settings()
    primary_model = force_primary_model or select_primary_model(query_for_routing)
    fallback_model = get_model_config().generator
    budget_s = settings.model_router_latency_budget_ms / 1000

    async def call(model: str, wait_s: float) -> str:
        # Streaming: the budget is time to the first token, so a model that has started
        # writing a long answer is not cut off mid-sentence.
        if stream:
            return await stream_complete(
                prompt,
                model=model,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                first_token_timeout=wait_s,
            )
        return await complete(
            prompt,
            model=model,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=wait_s,
        )

    start = time.perf_counter()
    try:
        answer = await call(primary_model, budget_s)
        return RoutedCompletion(
            answer=answer,
            primary_model=primary_model,
            model_used=primary_model,
            fell_back=False,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
    except LlmUnavailableError:
        pass  # fall through to the backup model below — a real retry, not a canned outcome

    # The fast model missing the budget usually means it was still loading into memory, so
    # it gets one more try with a full-length wait rather than no answer at all.
    answer = await call(fallback_model, FALLBACK_TIMEOUT_SECONDS)
    return RoutedCompletion(
        answer=answer,
        primary_model=primary_model,
        model_used=fallback_model,
        fell_back=fallback_model != primary_model,
        latency_ms=(time.perf_counter() - start) * 1000,
    )
