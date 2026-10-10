"""Output guardrail layer: Llama Guard output classification, a PII leak check, a system-
prompt/secret leak check, and mandatory citations. The faithfulness gate itself is the Verifier
(app/agents/verifier.py) in agentic mode — this layer doesn't duplicate claim-level checking,
it enforces the things that apply uniformly across *all* RAG modes (hybrid/graph included,
which have no dedicated Verifier step).
"""

from __future__ import annotations

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


def _redact_pii(answer: str) -> tuple[str, int]:
    detected = detect(answer)
    if not detected:
        return answer, 0
    redacted = answer
    for ent in sorted(detected, key=lambda e: e.start, reverse=True):
        redacted = (
            redacted[: ent.start] + mask_preview(ent.entity_type, ent.text) + redacted[ent.end :]
        )
    return redacted, len(detected)


async def check_output(
    answer: str,
    citations: Sequence[Mapping[str, Any]],
    session_id: str,
    trace_id: str,
    reveal_pii: bool = False,
) -> GuardrailResult:
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
        redacted_answer, leak_count = _redact_pii(answer)
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

    guard_verdict = await llama_guard_classify(answer, role="agent")
    # S7 is Llama Guard's "Privacy" category — a context-free classifier, it has no idea
    # whether disclosing this PII was actually authorized. When reveal_pii is true, the vault
    # already made that call with real context Llama Guard lacks (session-level authorization),
    # so an S7-only flag doesn't override it. Any *other* category still blocks regardless —
    # observed live: it flagged a legitimately-authorized "[email] is on file" answer as S7 at
    # reveal_pii=True, which is this exact false-positive case (see docs/DECISIONS.md).
    privacy_only = guard_verdict.category == "S7"
    if not guard_verdict.is_safe and not (reveal_pii and privacy_only):
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
