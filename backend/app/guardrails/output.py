"""Output guardrail layer: Llama Guard output classification, a PII leak check, a system-
prompt/secret leak check, and mandatory citations. The faithfulness gate itself is the Verifier
(app/agents/verifier.py) in agentic mode — this layer doesn't duplicate claim-level checking,
it enforces the things that apply uniformly across *all* RAG modes (hybrid/graph included,
which have no dedicated Verifier step).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.guardrails.audit import record as audit_record
from app.guardrails.llama_guard import classify as llama_guard_classify
from app.privacy.detector import detect
from app.privacy.tokenizer import mask_preview

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"UNTRUSTED_CONTEXT"),
    re.compile(r"you answer questions using only the numbered context", re.I),
]

_ABSTENTION_PHRASES = ("don't have enough", "do not have enough", "unable to generate")


@dataclass
class GuardrailResult:
    decision: str  # "allow" | "redact" | "block" | "escalate"
    rule: str
    reason: str
    answer: str
    score: float | None = None


# Tokens that stand in for personal data masked at upload, e.g. <PERSON_fafb3f>.
_MASK_TOKEN_RE = re.compile(r"<[A-Z][A-Z_]*_[0-9a-f]{6,}>")


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _redact_pii(answer: str, sources: Sequence[str] = ()) -> tuple[str, int]:
    """Masks personal data in the answer that did not come from the document as stored.

    Two things this must not do. It must not be misled by the mask tokens themselves: next
    to "<PERSON_fafb3f> for Facebook Messenger" the name detector called "Facebook
    Messenger" a person. Tokens are blanked (same length, so offsets hold) before detection.
    And it must not mask text the answer quotes from the document: the document was already
    masked at upload, so anything still present verbatim in a cited passage was judged not to
    be personal data then."""
    scan = _MASK_TOKEN_RE.sub(lambda m: " " * len(m.group(0)), answer)
    squashed_sources = [_squash(source) for source in sources]

    def from_source(text: str) -> bool:
        if any(text in source for source in sources):
            return True
        # Spacing and case ignored, for names long enough not to hide inside another word:
        # the answer may write "Dialogflow" where the passage has "Dialog flow".
        key = _squash(text)
        return len(key) >= 6 and any(key in source for source in squashed_sources)

    detected = [ent for ent in detect(scan) if ent.text.strip() and not from_source(ent.text)]
    if not detected:
        return answer, 0
    redacted = answer
    for ent in sorted(detected, key=lambda e: e.start, reverse=True):
        redacted = (
            redacted[: ent.start] + mask_preview(ent.entity_type, ent.text) + redacted[ent.end :]
        )
    return redacted, len(detected)


logger = logging.getLogger(__name__)

_SOURCE_DEPENDENT_CATEGORIES = frozenset({"S5", "S6", "S7", "S8"})


async def check_output(
    answer: str,
    citations: Sequence[Mapping[str, Any]],
    session_id: str,
    trace_id: str,
    reveal_pii: bool = False,
    question: str | None = None,
    sources: Sequence[str] = (),
) -> GuardrailResult:
    """`sources`: the full text of the passages the answer was written from. Text found
    verbatim there is the document's own, already masked at upload, and is not a leak."""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(answer):
            result = GuardrailResult(
                "block",
                "secret_leak",
                "Response referenced internal prompt/secret material.",
                answer="I can't share that — it looks like it would leak internal system details.",
            )
            await audit_record(
                trace_id, session_id, "output", result.rule, result.decision, excerpt=answer
            )
            return result

    if not reveal_pii:
        # The user's own question counts too: repeating a word they typed leaks nothing.
        known = [*sources, *(str(c.get("text", "")) for c in citations), question or ""]
        redacted_answer, leak_count = _redact_pii(answer, known)
        if leak_count:
            result = GuardrailResult(
                "redact",
                "pii_leak",
                f"Redacted {leak_count} PII value(s) not authorized for reveal.",
                answer=redacted_answer,
            )
            await audit_record(
                trace_id, session_id, "output", result.rule, result.decision, excerpt=answer
            )
            return result

    guard_verdict = await llama_guard_classify(answer, role="agent", question=question)
    # S7 is Llama Guard's "Privacy" category — a context-free classifier, it has no idea
    # whether disclosing this PII was actually authorized. When reveal_pii is true, the vault
    # already made that call with real context Llama Guard lacks (session-level authorization),
    # so an S7-only flag doesn't override it. Any *other* category still blocks regardless —
    # observed live: it flagged a legitimately-authorized "[email] is on file" answer as S7 at
    # reveal_pii=True, which is this exact false-positive case (see docs/DECISIONS.md).
    privacy_only = guard_verdict.category == "S7"
    # Defamation (S5), specialised advice (S6), privacy (S7) and intellectual property (S8)
    # are judgements about where a statement came from, which a context-free classifier
    # cannot make: the small guard model raises them for ordinary sentences such as "travel
    # over $5,000 needs the CFO's approval" or "the review is signed off by <name>". Answers
    # here are written from the user's own retrieved document, the PII scan above has already
    # run, and an answer with no citation is escalated by the check below — so these are
    # logged for review instead of replacing the answer. Every other category — violence,
    # crime, weapons, hate, self-harm, sexual content — still blocks.
    category = (guard_verdict.category or "").strip().upper()[:3].rstrip(",. ")
    sourced_statement = category in _SOURCE_DEPENDENT_CATEGORIES
    if sourced_statement:
        await audit_record(
            trace_id, session_id, "output", "llama_guard_output", "escalate", excerpt=answer
        )
    if not guard_verdict.is_safe and not (reveal_pii and privacy_only) and not sourced_statement:
        logger.warning(
            "Output guard blocked an answer: category=%r citations=%d",
            guard_verdict.category,
            len(citations),
        )
        result = GuardrailResult(
            "block",
            "llama_guard_output",
            f"Flagged unsafe content ({guard_verdict.category}).",
            answer="I can't provide that response.",
        )
        await audit_record(
            trace_id, session_id, "output", result.rule, result.decision, excerpt=answer
        )
        return result

    is_hedged = any(phrase in answer.lower() for phrase in _ABSTENTION_PHRASES)
    if not citations and not is_hedged and len(answer) > 40:
        result = GuardrailResult(
            "escalate",
            "missing_citations",
            "Answer made claims without citing any source — flagged for review.",
            answer=answer,
        )
        await audit_record(
            trace_id, session_id, "output", result.rule, result.decision, excerpt=answer
        )
        return result

    result = GuardrailResult("allow", "output_checks", "No issues detected.", answer=answer)
    await audit_record(trace_id, session_id, "output", result.rule, result.decision, excerpt=answer)
    return result
