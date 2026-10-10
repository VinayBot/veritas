"""Community summaries: a short description of what a Louvain-detected cluster of entities is
'about', from an LLM given the member names. Falls back to a plain entity list if the LLM is
unavailable — same degrade-gracefully pattern as HyDE and triple extraction.
"""

from __future__ import annotations

import logging

from app.llm.client import LlmUnavailableError, complete

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = (
    "These entities were grouped together because they are closely related in a document "
    "graph: {names}. In one short sentence, describe what connects them or what topic they "
    "share. Do not just list the entities back; describe the theme."
)


async def summarize_community(entity_names: list[str], model: str | None = None) -> str:
    fallback = "Entities: " + ", ".join(entity_names[:8])
    if len(entity_names) < 2:
        return fallback
    try:
        summary = await complete(
            _SUMMARY_PROMPT.format(names=", ".join(entity_names[:20])),
            model=model,
            max_tokens=80,
            temperature=0.2,
        )
        return summary.strip() or fallback
    except LlmUnavailableError:
        logger.info("Community summary: LLM unavailable, using fallback entity list")
        return fallback
