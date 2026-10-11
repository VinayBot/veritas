"""One LiteLLM-backed entry point for every stage that calls a model — local Ollama by
default, Groq/Gemini optionally via env vars (see .env.example). Every caller goes through
`complete()` so swapping providers never means touching call sites.

Also owns the per-run LLM-call budget (Fix 1 — see docs/DECISIONS.md): the agent graph can
chain a dozen-plus sequential model calls with no aggregate ceiling, which is one of the
mechanisms behind a turn that never finishes. `reset_llm_call_budget()` is called once at the
top of `run_chat_turn`; every `complete()` call thereafter (planner, rewriter, critic, council,
judge — anything in that same async call chain) consumes one unit via a ContextVar, which
propagates through nested `await`s within a task without threading a counter through every
function signature. A budget check deliberately raises instead of silently degrading like the
`LlmUnavailableError` call sites do — running out of budget should end the turn visibly, not be
swallowed into "proceed as if nothing happened."
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class LlmUnavailableError(Exception):
    pass


class LlmBudgetExceededError(Exception):
    pass


# A mutable single-element list, not a plain int, so nested calls can decrement the same
# counter the ContextVar points at rather than each seeing their own copy.
_llm_call_budget: ContextVar[list[int] | None] = ContextVar("_llm_call_budget", default=None)


def reset_llm_call_budget(max_calls: int) -> None:
    _llm_call_budget.set([max_calls])


def clear_llm_call_budget() -> None:
    _llm_call_budget.set(None)


def _consume_budget(model_name: str) -> None:
    budget = _llm_call_budget.get()
    if budget is None:  # no budget set for this context (e.g. a non-chat call site) — unbounded
        return
    if budget[0] <= 0:
        raise LlmBudgetExceededError(
            f"Per-run LLM call budget exhausted before calling {model_name!r}"
        )
    budget[0] -= 1


async def complete(
    prompt: str,
    model: str | None = None,
    system: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.2,
    timeout: float = 30.0,
) -> str:
    import litellm

    settings = get_settings()
    model_name = model or settings.default_llm_model
    _consume_budget(model_name)
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
    }
    if model_name.startswith("ollama/"):
        kwargs["api_base"] = settings.ollama_base_url

    try:
        response = await litellm.acompletion(**kwargs)
    except Exception as exc:  # LiteLLM raises many provider-specific exception types.
        logger.warning("LLM call to %s failed: %s", model_name, exc)
        raise LlmUnavailableError(f"{model_name} unavailable: {exc}") from exc

    content = response.choices[0].message.content
    return content or ""
