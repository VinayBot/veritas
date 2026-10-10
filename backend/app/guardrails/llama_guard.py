"""Llama Guard wrapper: classifies text as safe/unsafe for either the input or output
guardrail layer. Falls back to "safe" when the model is unavailable — for a local system,
blocking everything because one classifier is down is worse than losing one signal; the other
independent checks (regex, DeBERTa, faithfulness, PII scan) still run regardless.
"""

from __future__ import annotations

import logging

from app.core.config import get_settings
from app.llm.client import LlmUnavailableError, complete

logger = logging.getLogger(__name__)


class GuardVerdict:
    def __init__(self, is_safe: bool, category: str | None = None):
        self.is_safe = is_safe
        self.category = category


async def classify(text: str, role: str = "user") -> GuardVerdict:
    """`role` is "user" (classifying input) or "agent" (classifying the model's own output)."""
    settings = get_settings()
    prompt = (
        f"Task: Check if there is unsafe content in the {role} message below.\n\n"
        f"{role.capitalize()} message: {text}\n\n"
        "Respond with 'safe' or 'unsafe'. If unsafe, add the violation category on a new line."
    )
    try:
        raw = await complete(prompt, model=settings.guard_model, max_tokens=20, temperature=0.0)
    except LlmUnavailableError:
        logger.info("Llama Guard unavailable, defaulting to safe for this signal")
        return GuardVerdict(is_safe=True)

    stripped = raw.strip()
    if stripped.lower().startswith("unsafe"):
        category = stripped.split("\n", 1)[1].strip() if "\n" in stripped else None
        return GuardVerdict(is_safe=False, category=category)
    return GuardVerdict(is_safe=True)
