"""Verifier: claim-level faithfulness check against the retrieved context. Unsupported claims
trigger one revision pass (back to the Synthesizer). If some are still unsupported after
that, those sentences are removed and the supported rest is kept; the agent abstains only
when less than half of the answer survives, or when the flagged claims cannot be located.
"""

from __future__ import annotations

from app.agents.answer_style import _sentences
from app.agents.citations import citation_markers
from app.agents.context_utils import build_numbered_context
from app.agents.state import MAX_REVISE_LOOPS, AgentState, record_step
from app.core.tracing import trace_bus
from app.evaluation.grounding import is_claim_in_answer, unsupported_claims
from app.llm.models_config import get_model_config


async def verifier_node(state: AgentState) -> dict:
    answer = state.get("answer", "")
    retrieved = state.get("retrieved", [])
    context = build_numbered_context(retrieved)
    revise_count = state.get("revise_count", 0)

    async with trace_bus.stage(
        state["session_id"], "verifier", from_stage="synthesizer", to_stage="guardian_out"
    ) as h:
        config = get_model_config()
        # Reproduced live (see docs/TROUBLESHOOTING.md): DEFAULT_LLM_MODEL (llama3.2:3b)
        # flagged a sentence copied almost verbatim from the context as "unsupported" —
        # the same multi-clause reasoning weakness as the Critic's answerability check
        # (critic.py), fixed the same way: use the system's designated stronger model
        # (council_models[0]) for this specific judgment call, which got it right in the
        # same live comparison. The Synthesizer's own answer generation is unaffected and
        # keeps using the fast complexity-based router.
        # force_fast (the post-timeout retry — see docs/DECISIONS.md) overrides this to the
        # fast default model regardless: a live timed run measured this stronger model's
        # calls at ~20-30s each on this project's own 16GB-tier hardware, which is exactly
        # the cost the retry exists to avoid repeating.
        grading_model = config.generator if state.get("force_fast") else config.stronger_model()
        # None (the check could not run) is treated like "nothing flagged": the answer is
        # not blocked on a verifier that is unavailable.
        unsupported = await unsupported_claims(answer, context, model=grading_model) or []

        trimmed: str | None = None
        if not unsupported:
            verdict = "supported"
        elif revise_count < MAX_REVISE_LOOPS:
            verdict = "revise"
        else:
            trimmed = supported_part(answer, unsupported)
            verdict = "trimmed" if trimmed else "abstain"

        h.set_metric("verdict", verdict)
        h.set_metric("unsupported_count", len(unsupported))
        h.set_output(f"verdict={verdict}, {len(unsupported)} unsupported claim(s)")

    summaries = {
        "supported": "Verified the answer is fully supported by the retrieved context.",
        "revise": f"Found {len(unsupported)} unsupported claim(s); requesting a revision.",
        "abstain": "Could not support enough of the answer after revision; abstaining.",
        "trimmed": f"Removed {len(unsupported)} unsupported sentence(s) after revision; kept the "
        "supported rest.",
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
    if verdict == "trimmed" and trimmed is not None:
        kept = set(citation_markers(trimmed))
        result["answer"] = trimmed
        result["citations"] = [c for c in state.get("citations", []) if c["marker"] in kept]
    return result


def supported_part(answer: str, unsupported: list[str]) -> str | None:
    """The answer without the sentences the verifier could not support, or None when that
    leaves less than half of it — or when a flagged claim matches no sentence, since then it
    is not known which part is unsupported."""
    sentences = _sentences(answer)
    if not sentences:
        return None
    flagged = set()
    for claim in unsupported:
        matches = [i for i, sentence in enumerate(sentences) if is_claim_in_answer(claim, sentence)]
        if not matches:
            return None
        flagged.update(matches)
    kept = [s for i, s in enumerate(sentences) if i not in flagged]
    if not kept or len(kept) * 2 < len(sentences):
        return None
    return " ".join(kept)


def route_after_verifier(state: AgentState) -> str:
    return "revise" if state.get("verifier_verdict") == "revise" else "proceed"
