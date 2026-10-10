"""Retrieval-layer guardrail: scans retrieved/scraped content for injection attempts before it
reaches the Synthesizer (Section 10's "indirect injection via document"). Flagged chunks are
kept, not dropped — real content that happens to quote or discuss an injection attempt would be
wrongly censored by dropping it outright — but every flag is audited, and the Synthesizer wraps
*all* context in untrusted-data delimiters with an explicit instruction hierarchy regardless of
whether anything was flagged (app/agents/context_utils.py).
"""

from __future__ import annotations

from typing import Any

from app.guardrails import injection
from app.guardrails.audit import record as audit_record

SCORE_THRESHOLD = 0.5


async def scan_hits(
    hits: list[dict[str, Any]], session_id: str, trace_id: str
) -> list[dict[str, Any]]:
    for hit in hits:
        verdict = injection.scan(hit.get("text", ""))
        hit["flagged_injection"] = bool(verdict.is_injection and verdict.score >= SCORE_THRESHOLD)
        if hit["flagged_injection"]:
            await audit_record(
                trace_id,
                session_id,
                "retrieval",
                "indirect_injection",
                "redact",
                score=verdict.score,
                excerpt=hit.get("text", ""),
            )
    return hits
