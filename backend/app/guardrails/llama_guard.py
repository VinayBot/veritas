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


# What stands in for the other side of the conversation when only one side is being checked.
_NEUTRAL_USER_TURN = "Answer my question using the document."


async def classify(text: str, role: str = "user", question: str | None = None) -> GuardVerdict:
    """`role` is "user" (classifying input) or "agent" (classifying the model's own output).
    `question` is what the answer was a reply to: the guard judges an answer in the context
    of its question, and without the real one it misreads ordinary policy text as advice.

    Llama Guard is trained on conversations rendered through its own chat template, which the
    model server applies to real user/assistant turns. Wrapping the text in a hand-written
    instruction instead makes it judge that instruction as the user message, and it then
    flags ordinary answers as unsafe."""
    settings = get_settings()
    model = settings.guard_model
    if model.startswith("ollama/"):
        model = "ollama_chat/" + model.removeprefix("ollama/")  # the chat API applies the template
    if role == "agent":
        messages = [
            {"role": "user", "content": question or _NEUTRAL_USER_TURN},
            {"role": "assistant", "content": text},
        ]
    else:
        messages = [{"role": "user", "content": text}]
    try:
        raw = await complete("", model=model, max_tokens=20, temperature=0.0, messages=messages)
    except LlmUnavailableError:
        logger.info("Llama Guard unavailable, defaulting to safe for this signal")
        return GuardVerdict(is_safe=True)

    stripped = raw.strip()
    if stripped.lower().startswith("unsafe"):
        category = stripped.split("\n", 1)[1].strip() if "\n" in stripped else None
        return GuardVerdict(is_safe=False, category=category)
    return GuardVerdict(is_safe=True)
