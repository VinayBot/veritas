"""Input guardrail layer: rate limiting, length/encoding checks, and prompt-injection detection
(regex + DeBERTa + Llama Guard — three independent signals, since live testing showed they
catch genuinely different things: Llama Guard flags unsafe *content*, the DeBERTa classifier
and regexes flag injection/jailbreak *framing*, and a message can trip either without the
other — see docs/DECISIONS.md). The "scope" check from Section 10 is deliberately not a
separate step here: the Planner (Phase 6) already classifies `out_of_scope` as part of query
classification, and app/agents/graph.py routes that straight to a decline rather than running
retrieval — duplicating a second scope classifier here would just re-answer the same question
the Planner already answers slightly later in the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.guardrails import encoding, injection, rate_limit
from app.guardrails.audit import record as audit_record
from app.guardrails.llama_guard import classify as llama_guard_classify

INJECTION_SCORE_THRESHOLD = 0.5


@dataclass
class GuardrailResult:
    decision: str  # "allow" | "block" | "escalate"
    rule: str
    reason: str
    score: float | None = None


async def check_input(text: str, session_id: str, trace_id: str) -> GuardrailResult:
    if not rate_limit.check(session_id):
        result = GuardrailResult("block", "rate_limit", "Too many requests in the last minute.")
        await audit_record(
            trace_id, session_id, "input", result.rule, result.decision, excerpt=text
        )
        return result

    issues = encoding.check(text)
    if issues:
        kinds = {i.kind for i in issues}
        rule = "too_long" if "too_long" in kinds else "suspicious_encoding"
        result = GuardrailResult("block", rule, f"Input flagged by: {', '.join(sorted(kinds))}")
        await audit_record(
            trace_id, session_id, "input", result.rule, result.decision, excerpt=text
        )
        return result

    injection_verdict = injection.scan(text)
    if injection_verdict.is_injection and injection_verdict.score >= INJECTION_SCORE_THRESHOLD:
        result = GuardrailResult(
            "block",
            "prompt_injection",
            "Detected a likely prompt injection or jailbreak attempt.",
            score=injection_verdict.score,
        )
        await audit_record(
            trace_id,
            session_id,
            "input",
            result.rule,
            result.decision,
            score=injection_verdict.score,
            excerpt=text,
        )
        return result

    guard_verdict = await llama_guard_classify(text, role="user")
    if not guard_verdict.is_safe:
        result = GuardrailResult(
            "block", "llama_guard", f"Flagged unsafe content ({guard_verdict.category})."
        )
        await audit_record(
            trace_id, session_id, "input", result.rule, result.decision, excerpt=text
        )
        return result

    result = GuardrailResult("allow", "input_checks", "No issues detected.")
    await audit_record(trace_id, session_id, "input", result.rule, result.decision, excerpt=text)
    return result
