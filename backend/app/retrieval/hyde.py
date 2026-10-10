"""HyDE: generate a hypothetical answer and embed *that* instead of (or alongside) the raw
query. A short passage tends to sit closer in embedding space to real answer passages than a
question does. Falls back to the raw query if the LLM is unavailable — a search feature should
degrade gracefully, not fail outright, when Ollama isn't running.
"""

from __future__ import annotations

import logging

from app.llm.client import LlmUnavailableError, complete

logger = logging.getLogger(__name__)

_HYDE_PROMPT = (
    "Write a short, plausible passage (2-4 sentences) that would directly answer this "
    "question, as if it were an excerpt from a real document. Do not mention that you are "
    "guessing or that this is hypothetical — just write the passage itself.\n\n"
    "Question: {query}"
)


async def hyde_rewrite(query: str, model: str | None = None) -> str:
    try:
        hypothetical = await complete(
            _HYDE_PROMPT.format(query=query), model=model, max_tokens=200, temperature=0.3
        )
        return hypothetical.strip() or query
    except LlmUnavailableError:
        logger.info("HyDE: LLM unavailable, falling back to the raw query")
        return query
