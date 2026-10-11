"""Critic (corrective RAG): grades retrieved context on two independent signals — the best
cross-encoder relevance score already attached by the Retriever's hybrid_search tool, and a
direct LLM answerability judgment — and decides whether to retry with a different rewrite
technique.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.agents.state import MAX_CRITIC_LOOPS, AgentState, record_step
from app.core.config import get_settings
from app.core.tracing import trace_bus
from app.llm.client import LlmUnavailableError, complete

SCORE_THRESHOLD = 0.3

_GRADE_PROMPT = (
    "Context:\n{context}\n\nQuestion: {query}\n\n"
    "Does the context above contain enough information to determine the answer to the "
    "question, even if that answer is restrictive or negative (for example 'no, not without "
    "approval')? Judge only whether the information needed is present, not what the answer "
    "turns out to be. Reply with exactly one word: ANSWERABLE or UNANSWERABLE."
)


async def _llm_grade(query: str, hits: Sequence[Mapping[str, Any]]) -> bool:
    """Reproduced live (see docs/TROUBLESHOOTING.md): rewording the reply tokens to
    ANSWERABLE/UNANSWERABLE wasn't enough on its own — DEFAULT_LLM_MODEL (llama3.2:3b) still
    answered the *object-level* question ('no, not without approval') instead of judging
    answerability, for every question whose real answer is restrictive or negative, regardless
    of retrieval quality. qwen2.5:7b-instruct (already the system's designated stronger model —
    see select_primary_model) got every case right in the same live comparison, so this one
    judgment call is worth its extra latency over the default."""
    if not hits:
        return False
    # Full chunk text, not a slice — see the matching fix in context_utils.py. A 300-char
    # slice here cut off before the sentence that actually answered a live golden question
    # (it only reached the chunk's opening paragraph), so the grading model judged the real,
    # relevant sentence it never saw as absent. See docs/TROUBLESHOOTING.md.
    context = "\n---\n".join(h["text"] for h in hits)
    settings = get_settings()
    grading_model = settings.council_model_list[0] if settings.council_model_list else None
    try:
        raw = await complete(
            _GRADE_PROMPT.format(context=context, query=query),
            model=grading_model,
            max_tokens=10,
            temperature=0.0,
        )
        return raw.strip().upper().startswith("ANSWERABLE")
    except LlmUnavailableError:
        return True  # Can't verify this signal — fall back to the score alone, don't block on it.


async def critic_node(state: AgentState) -> dict:
    retrieved = state.get("retrieved", [])
    loop_count = state.get("loop_count", 0)

    async with trace_bus.stage(
        state["session_id"], "critic", from_stage="retriever", to_stage="synthesizer"
    ) as h:
        if not retrieved:
            score, verdict = 0.0, "insufficient"
        else:
            top = retrieved[:5]
            # The best hit, not the mean — a real top-k result set normally mixes one or two
            # genuinely relevant chunks with several unrelated ones (that's expected hybrid
            # retrieval noise, not a bad retrieval), and the cross-encoder's negative scores for
            # "irrelevant" run much larger in magnitude than its positive scores for "relevant"
            # (observed: +4.6 for a correct top hit vs. -8 to -11 for the filler alongside it).
            # Averaging let 3 irrelevant chunks veto 1 excellent one; see docs/TROUBLESHOOTING.md.
            best_score = max(r["score"] for r in top)
            llm_says_yes = await _llm_grade(state["query"], top)
            score = best_score
            verdict = (
                "sufficient" if (best_score > SCORE_THRESHOLD and llm_says_yes) else "insufficient"
            )
        h.set_metric("best_score", score)
        h.set_metric("verdict", verdict)
        h.set_metric("loop_count", loop_count)
        h.set_output(f"verdict={verdict} best_score={score:.3f}")

    summary = f"Judged evidence as {verdict} (best relevance {score:.2f})."
    return {
        "critic_score": score,
        "critic_verdict": verdict,
        "loop_count": loop_count + 1 if verdict == "insufficient" else loop_count,
        "agent_steps": record_step(state, "critic", summary),
    }


def route_after_critic(state: AgentState) -> str:
    if (
        state.get("critic_verdict") == "insufficient"
        and state.get("loop_count", 0) < MAX_CRITIC_LOOPS
    ):
        return "retry"
    return "proceed"
