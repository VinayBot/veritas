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

import asyncio
import logging
import weakref
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

from app.core.config import get_settings
from app.llm.models_config import get_model_config

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


# Real token counts as reported by the provider, accumulated across every call made while a
# collector is active. Same mutable-object-in-a-ContextVar approach as the budget above.
_usage: ContextVar[dict[str, Any] | None] = ContextVar("_llm_usage", default=None)


def start_usage_collection() -> dict[str, Any]:
    usage: dict[str, Any] = {
        "llm_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "by_model": {},
        # Calls where the provider returned no usage block; their tokens are not in the totals.
        "calls_without_usage": 0,
    }
    _usage.set(usage)
    return usage


def stop_usage_collection() -> None:
    _usage.set(None)


def _record_usage(model_name: str, response: Any) -> None:
    usage = _usage.get()
    if usage is None:
        return
    usage["llm_calls"] += 1
    per_model = usage["by_model"].setdefault(
        model_name, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    )
    per_model["calls"] += 1
    reported = getattr(response, "usage", None)
    prompt = getattr(reported, "prompt_tokens", None)
    completion = getattr(reported, "completion_tokens", None)
    if prompt is None or completion is None:
        usage["calls_without_usage"] += 1
        return
    usage["prompt_tokens"] += int(prompt)
    usage["completion_tokens"] += int(completion)
    per_model["prompt_tokens"] += int(prompt)
    per_model["completion_tokens"] += int(completion)


# ---- Chat goes first -------------------------------------------------------------------
# A local model server answers one request at a time, so a judge call or a graph-extraction
# call that is already queued makes the person waiting for an answer wait behind it. Work
# marked as background (scoring, enrichment, evaluation jobs) holds off before each model
# call while an interactive answer is being generated.
_interactive_turns = 0


class _LoopState:
    """Synchronisation primitives belong to one event loop. Keeping them per loop means a
    second loop (each test gets its own) never touches objects bound to a finished one."""

    def __init__(self) -> None:
        self.idle = asyncio.Event()
        self.idle.set()
        self.busy = asyncio.Event()
        self.slots = asyncio.Semaphore(max(1, get_settings().llm_max_concurrency))


_loop_states: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopState] = (
    weakref.WeakKeyDictionary()
)


def _state() -> _LoopState:
    loop = asyncio.get_running_loop()
    state = _loop_states.get(loop)
    if state is None:
        state = _loop_states[loop] = _LoopState()
    return state


_background: ContextVar[bool] = ContextVar("_llm_background", default=False)
BACKGROUND_MAX_WAIT_SECONDS = 60.0


def _idle() -> asyncio.Event:
    return _state().idle


def _busy() -> asyncio.Event:
    return _state().busy


@asynccontextmanager
async def interactive() -> AsyncIterator[None]:
    """Marks the enclosed model calls as someone waiting for an answer."""
    global _interactive_turns
    _interactive_turns += 1
    _idle().clear()
    _busy().set()
    try:
        yield
    finally:
        _interactive_turns -= 1
        if _interactive_turns <= 0:
            _interactive_turns = 0
            _idle().set()
            _busy().clear()


def mark_background() -> None:
    """Every model call made by this task from here on yields to interactive answers."""
    _background.set(True)


async def _yield_to_interactive() -> None:
    if not _background.get() or _idle().is_set():
        return
    try:
        await asyncio.wait_for(_idle().wait(), timeout=BACKGROUND_MAX_WAIT_SECONDS)
    except TimeoutError:
        pass  # never starve background work indefinitely


@asynccontextmanager
async def _local_slot(model_name: str) -> AsyncIterator[None]:
    """Waits for a turn at the local model server. The wait happens here, before the request
    is sent, so a call's timeout measures the model and not the queue in front of it."""
    if not model_name.startswith(("ollama/", "ollama_chat/")):
        yield
        return
    async with _state().slots:
        yield


MAX_PREEMPTIONS = 4


async def _preemptible(start: Callable[[], Awaitable[Any]]) -> Any:
    """Runs a background model call, abandoning and restarting it if someone asks a question
    meanwhile. Dropping the connection makes the model server stop generating, which frees it
    for the interactive answer; the background call starts over once chat is idle again."""
    for _ in range(MAX_PREEMPTIONS):
        await _yield_to_interactive()
        call = asyncio.ensure_future(start())
        busy = asyncio.ensure_future(_busy().wait())
        try:
            await asyncio.wait({call, busy}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            busy.cancel()
            if not call.done():
                call.cancel()
        if call.done() and not call.cancelled():
            return call.result()
        try:
            await call
        except BaseException:  # noqa: BLE001 — the abandoned call's outcome is irrelevant
            pass
        if asyncio.current_task() and asyncio.current_task().cancelling():  # type: ignore[union-attr]
            raise asyncio.CancelledError
    return await start()  # preempted repeatedly: let it finish rather than starve


# ---- Live token streaming --------------------------------------------------------------
# When a sink is set, `stream_complete` hands it each piece of text as the model writes it.
TokenSink = Callable[[str], Awaitable[None]]
_token_sink: ContextVar[TokenSink | None] = ContextVar("_llm_token_sink", default=None)


def set_token_sink(sink: TokenSink | None) -> None:
    _token_sink.set(sink)


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
    messages: list[dict[str, str]] | None = None,
) -> str:
    """`messages`, when given, replaces the single-prompt conversation built from `prompt`
    and `system` — for models that need real user/assistant turns (Llama Guard)."""
    import litellm

    settings = get_settings()
    model_name = model or get_model_config().generator
    _consume_budget(model_name)
    if messages is None:
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
    if model_name.startswith(("ollama/", "ollama_chat/")):
        kwargs["api_base"] = settings.ollama_base_url

    try:

        async def send() -> Any:
            async with _local_slot(model_name):
                return await litellm.acompletion(**kwargs)

        response = await (_preemptible(send) if _background.get() else send())
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # LiteLLM raises many provider-specific exception types.
        logger.warning("LLM call to %s failed: %s", model_name, exc)
        raise LlmUnavailableError(f"{model_name} unavailable: {exc}") from exc

    _record_usage(model_name, response)
    content = response.choices[0].message.content
    return content or ""


async def stream_complete(
    prompt: str,
    model: str | None = None,
    system: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.2,
    first_token_timeout: float = 30.0,
    timeout: float = 90.0,
) -> str:
    """`complete()`, but the text is handed to the active token sink as it is written. The
    short timeout applies to the first token only — a model that has started writing is not
    cut off for writing a long answer. Without a sink this is a plain `complete()`."""
    sink = _token_sink.get()
    if sink is None:
        return await complete(
            prompt, model, system, max_tokens, temperature, timeout=first_token_timeout
        )

    import litellm

    settings = get_settings()
    model_name = model or get_model_config().generator
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
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if model_name.startswith("ollama/"):
        kwargs["api_base"] = settings.ollama_base_url

    parts: list[str] = []
    last_chunk: Any = None
    try:
        async with _local_slot(model_name):
            stream = await asyncio.wait_for(litellm.acompletion(**kwargs), first_token_timeout)
            iterator = stream.__aiter__()
            deadline = asyncio.get_running_loop().time() + timeout
            while True:
                wait = (
                    first_token_timeout
                    if not parts
                    else max(1.0, deadline - asyncio.get_running_loop().time())
                )
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), wait)
                except StopAsyncIteration:
                    break
                last_chunk = chunk
                choices = getattr(chunk, "choices", None) or []
                piece = getattr(choices[0].delta, "content", None) if choices else None
                if piece:
                    parts.append(piece)
                    await sink(piece)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — provider-specific errors and timeouts alike
        logger.warning("Streaming LLM call to %s failed: %s", model_name, exc or type(exc).__name__)
        raise LlmUnavailableError(f"{model_name} unavailable: {exc}") from exc

    _record_usage(model_name, last_chunk)
    return "".join(parts)
