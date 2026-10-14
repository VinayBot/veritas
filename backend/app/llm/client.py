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
# call that is already queued makes the person waiting for an answer wait behind it.
# Three levels. 0: someone is waiting for a chat answer. 1: work the user started and is
# watching (a comparison, an evaluation, scoring the answer just given). 2: housekeeping
# nobody is watching (graph extraction after an upload). A call waits while anything of a
# lower number is active, and is abandoned and restarted if something lower starts.
CHAT, FOREGROUND, HOUSEKEEPING = 0, 1, 2


class _LoopState:
    """Synchronisation primitives belong to one event loop. Keeping them per loop means a
    second loop (each test gets its own) never touches objects bound to a finished one."""

    def __init__(self) -> None:
        self.active = {CHAT: 0, FOREGROUND: 0}
        self.changed = asyncio.Event()  # pulsed whenever `active` changes
        self.slots = asyncio.Semaphore(max(1, get_settings().llm_max_concurrency))

    def blocked(self, level: int) -> bool:
        return any(count > 0 for other, count in self.active.items() if other < level)

    def pulse(self) -> None:
        self.changed.set()
        self.changed = asyncio.Event()


_loop_states: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopState] = (
    weakref.WeakKeyDictionary()
)


def _state() -> _LoopState:
    loop = asyncio.get_running_loop()
    state = _loop_states.get(loop)
    if state is None:
        state = _loop_states[loop] = _LoopState()
    return state


_level: ContextVar[int] = ContextVar("_llm_level", default=CHAT)
BACKGROUND_MAX_WAIT_SECONDS = 90.0


@asynccontextmanager
async def _active(level: int) -> AsyncIterator[None]:
    state = _state()
    state.active[level] += 1
    state.pulse()
    try:
        yield
    finally:
        state.active[level] -= 1
        state.pulse()


def interactive() -> Any:
    """Marks the enclosed model calls as someone waiting for a chat answer."""
    return _active(CHAT)


def foreground_job() -> Any:
    """Marks the enclosed work as a job the user started; housekeeping waits for it."""
    return _active(FOREGROUND)


def mark_background(level: int = FOREGROUND) -> None:
    """Every model call made by this task from here on yields to more urgent work."""
    _level.set(level)


async def _yield_to_urgent() -> None:
    level = _level.get()
    state = _state()
    deadline = asyncio.get_running_loop().time() + BACKGROUND_MAX_WAIT_SECONDS
    while state.blocked(level):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return  # never starve background work indefinitely
        try:
            await asyncio.wait_for(state.changed.wait(), timeout=remaining)
        except TimeoutError:
            return


async def _until_blocked(level: int) -> None:
    state = _state()
    while not state.blocked(level):
        await state.changed.wait()


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
    """Runs a background model call, abandoning and restarting it if more urgent work
    arrives meanwhile. Dropping the connection makes the model server stop generating, which
    frees it at once; the call starts over when the urgent work is finished."""
    level = _level.get()
    for _ in range(MAX_PREEMPTIONS):
        await _yield_to_urgent()
        call = asyncio.ensure_future(start())
        urgent = asyncio.ensure_future(_until_blocked(level))
        try:
            await asyncio.wait({call, urgent}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            urgent.cancel()
            if not call.done():
                call.cancel()
        if call.done() and not call.cancelled():
            return call.result()
        try:
            await call
        except BaseException:  # noqa: BLE001 — the abandoned call's outcome is irrelevant
            pass
        task = asyncio.current_task()
        if task is not None and task.cancelling():
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


def _is_resident(model_name: str) -> bool:
    settings = get_settings()
    resident = {
        get_model_config().generator.split("/", 1)[-1],
        settings.guard_model.split("/", 1)[-1],
    }
    return model_name.split("/", 1)[-1] in resident


def _ollama_options(model_name: str) -> dict[str, Any]:
    if not model_name.startswith(("ollama/", "ollama_chat/")):
        return {}
    # An explicit context window. Ollama's default is 4096 tokens, and a longer prompt is cut
    # from the start without an error, which drops the instructions: the agent's summary
    # prompt (eight passages of up to 512 tokens plus notes) and its verifier prompt exceed
    # it. One value for every call, so a model is never reloaded for a different window.
    settings = get_settings()
    return {"api_base": settings.ollama_base_url, "num_ctx": settings.ollama_num_ctx}


async def _release(model_name: str) -> None:
    """Asks the local server to unload a model that is not one of the two kept in memory
    (the answer model and the guard model). A council member or a separately chosen judge is
    dropped as soon as it has replied, so picking an extra model never leaves three or four
    resident on a 16 GB machine. Sent to Ollama directly: the `keep_alive` request option is
    not forwarded on every LiteLLM route."""
    if not model_name.startswith(("ollama/", "ollama_chat/")) or _is_resident(model_name):
        return
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{get_settings().ollama_base_url}/api/generate",
                json={"model": model_name.split("/", 1)[1], "keep_alive": 0},
            )
    except httpx.HTTPError:
        pass  # the server will unload it on its own schedule


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
    kwargs.update(_ollama_options(model_name))

    try:

        async def send() -> Any:
            async with _local_slot(model_name):
                return await litellm.acompletion(**kwargs)

        response = await (_preemptible(send) if _level.get() > CHAT else send())
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # LiteLLM raises many provider-specific exception types.
        logger.warning("LLM call to %s failed: %s", model_name, exc)
        raise LlmUnavailableError(f"{model_name} unavailable: {exc}") from exc

    _record_usage(model_name, response)
    await _release(model_name)
    content = response.choices[0].message.content
    return content or ""


async def complete_tool_call(
    prompt: str,
    tool: dict[str, Any],
    model: str | None = None,
    system: str | None = None,
    max_tokens: int = 300,
    temperature: float = 0.0,
    timeout: float = 30.0,
) -> dict[str, Any] | None:
    """Native tool calling: the model is offered one function (an OpenAI-style tool schema)
    and must call it. Returns the call's arguments, or None when the model answered without a
    usable tool call. Ollama models go through LiteLLM's `ollama_chat/` route, which uses
    Ollama's /api/chat tool support rather than prompting for JSON."""
    import json

    import litellm

    model_name = model or get_model_config().generator
    if model_name.startswith("ollama/"):
        model_name = "ollama_chat/" + model_name.split("/", 1)[1]
    _consume_budget(model_name)
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    kwargs: dict = {
        "model": model_name,
        "messages": messages,
        "tools": [tool],
        "tool_choice": "required",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
    }
    kwargs.update(_ollama_options(model_name))
    try:

        async def send() -> Any:
            async with _local_slot(model_name):
                return await litellm.acompletion(**kwargs)

        response = await (_preemptible(send) if _level.get() > CHAT else send())
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — provider-specific exception types
        logger.warning("Tool call to %s failed: %s", model_name, exc)
        raise LlmUnavailableError(f"{model_name} unavailable: {exc}") from exc
    _record_usage(model_name, response)
    await _release(model_name)
    calls = response.choices[0].message.tool_calls or []
    wanted = tool["function"]["name"]
    for call in calls:
        if call.function.name != wanted:
            continue
        arguments = call.function.arguments
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


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
    kwargs.update(_ollama_options(model_name))

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
    await _release(model_name)
    return "".join(parts)
