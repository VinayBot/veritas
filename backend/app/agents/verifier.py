"""Verifier: claim-level faithfulness check against the retrieved context. Unsupported claims
trigger one revision pass (back to the Synthesizer); still unsupported after that -> abstain
rather than ship an answer the context doesn't back up.
"""

from __future__ import annotations

import re

from app.agents.context_utils import build_numbered_context
from app.agents.state import MAX_REVISE_LOOPS, AgentState, record_step
from app.core.config import get_settings
from app.core.tracing import trace_bus
from app.llm.client import LlmUnavailableError, complete
from app.llm.json_utils import extract_json_array

_VERIFY_PROMPT = (
    "Context:\n{context}\n\nAnswer to check:\n{answer}\n\n"
    "List any sentences in the answer that are NOT directly supported by the context, as a "
    "JSON array of strings (the exact unsupported sentences, copied verbatim). If every "
    "sentence is supported, return []. Return ONLY the JSON array, no other text."
)

_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize_words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _is_claim_grounded_in_answer(claim: str, answer: str) -> bool:
    """A real finding names a sentence that's actually IN the answer. Reproduced live against
    the local 3B verifier model (see docs/TROUBLESHOOTING.md's Bug B writeup): asked to flag
    unsupported sentences *in the answer*, it instead echoed a sentence copied from the
    *context* — syntactically valid JSON, semantically nonsense, since a context sentence
    doesn't need to be "supported by the context" at all. Exact substring would reject the
    common case of minor whitespace/punctuation drift, so this also accepts near-verbatim
    claims via word overlap — but a claim sharing almost no words with the answer at all is a
    model slip, not evidence, and must not be allowed to cause a false abstain."""
    normalized_answer = " ".join(answer.lower().split())
    normalized_claim = " ".join(claim.lower().split())
    if normalized_claim and normalized_claim in normalized_answer:
        return True
    claim_words = _normalize_words(claim)
    if not claim_words:
        return False
    overlap = claim_words & _normalize_words(answer)
    return len(overlap) / len(claim_words) >= 0.7


def _is_claim_grounded_in_context(claim: str, context: str) -> bool:
    """A claim quoted (near-)verbatim from the context is supported by definition, independent
    of the verifier model's own verdict about it. Reproduced live (see
    docs/TROUBLESHOOTING.md): given a longer, multi-section context (one real ~2600-char chunk
    plus 3 others), even the stronger council model occasionally flagged a character-for-
    character quote from the context as "not directly supported" — a claim this well-grounded
    shouldn't depend on the model noticing its own exact words. The bar is stricter than
    `_is_claim_grounded_in_answer` (0.9 vs 0.7): that function only screens out hallucinated
    *findings* (a looser bar costs nothing extra), but this one overrides a verdict the model
    actually reached, which calls for strong evidence, not a loose one."""
    normalized_context = " ".join(context.lower().split())
    normalized_claim = " ".join(claim.lower().split())
    if normalized_claim and normalized_claim in normalized_context:
        return True
    claim_words = _normalize_words(claim)
    if not claim_words:
        return False
    overlap = claim_words & _normalize_words(context)
    return len(overlap) / len(claim_words) >= 0.9


async def verifier_node(state: AgentState) -> dict:
    answer = state.get("answer", "")
    retrieved = state.get("retrieved", [])
    context = build_numbered_context(retrieved)
    revise_count = state.get("revise_count", 0)

    async with trace_bus.stage(
        state["session_id"], "verifier", from_stage="synthesizer", to_stage="guardian_out"
    ) as h:
        try:
            settings = get_settings()
            # Reproduced live (see docs/TROUBLESHOOTING.md): DEFAULT_LLM_MODEL (llama3.2:3b)
            # flagged a sentence copied almost verbatim from the context as "unsupported" —
            # the same multi-clause reasoning weakness as the Critic's answerability check
            # (critic.py), fixed the same way: use the system's designated stronger model
            # (council_models[0]) for this specific judgment call, which got it right in the
            # same live comparison. The Synthesizer's own answer generation is unaffected and
            # keeps using the fast complexity-based router.
            grading_model = settings.council_model_list[0] if settings.council_model_list else None
            raw = await complete(
                _VERIFY_PROMPT.format(context=context, answer=answer),
                model=grading_model,
                max_tokens=400,
                temperature=0.0,
            )
            unsupported = extract_json_array(raw) or []
            unsupported = [str(c) for c in unsupported if isinstance(c, str)]
            unsupported = [c for c in unsupported if _is_claim_grounded_in_answer(c, answer)]
            unsupported = [c for c in unsupported if not _is_claim_grounded_in_context(c, context)]
        except LlmUnavailableError:
            unsupported = []

        if not unsupported:
            verdict = "supported"
        elif revise_count < MAX_REVISE_LOOPS:
            verdict = "revise"
        else:
            verdict = "abstain"

        h.set_metric("verdict", verdict)
        h.set_metric("unsupported_count", len(unsupported))
        h.set_output(f"verdict={verdict}, {len(unsupported)} unsupported claim(s)")

    summaries = {
        "supported": "Verified the answer is fully supported by the retrieved context.",
        "revise": f"Found {len(unsupported)} unsupported claim(s); requesting a revision.",
        "abstain": "Could not fully support the answer after revision; abstaining.",
    }
    result: dict = {
        "verifier_verdict": verdict,
        "unsupported_claims": unsupported,
        "agent_steps": record_step(state, "verifier", summaries[verdict]),
    }
    if verdict == "revise":
        result["revise_count"] = revise_count + 1
    if verdict == "abstain":
        result["answer"] = "I don't have enough reliably-supported information to answer that."
        result["citations"] = []
    return result


def route_after_verifier(state: AgentState) -> str:
    return "revise" if state.get("verifier_verdict") == "revise" else "proceed"
