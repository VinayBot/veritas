"""One LiteLLM-backed entry point for every stage that calls a model — local Ollama by
default, Groq/Gemini optionally via env vars (see .env.example). Every caller goes through
`complete()` so swapping providers never means touching call sites.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class LlmUnavailableError(Exception):
    pass


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
