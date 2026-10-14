"""Critic (corrective RAG): grades retrieved context on two independent signals — the best
cross-encoder relevance score already attached by the Retriever's hybrid_search tool, and a
direct LLM answerability judgment — and decides whether to retry with a different rewrite
technique.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.agents.state import MAX_CRITIC_LOOPS, AgentState, record_step
from app.core.tracing import trace_bus
from app.llm.client import LlmUnavailableError, complete
from app.llm.models_config import get_model_config

SCORE_THRESHOLD = 0.3
# A cross-encoder score this high means the reranker is confident a passage answers the
# question (a correct top hit measured +4.6; unrelated passages -8 to -11). It stands on its
# own when the small grading model misreads a refusal ("may not … without approval") as
# missing information.
STRONG_SCORE = 3.0

_GRADE_PROMPT = (
    "Context:\n{context}\n\nQuestion: {query}\n\n"
    "Is the information needed to answer this question present in the context? A rule, a "
    "condition or a refusal in the context counts as information. Do not answer the question "
    "itself. Reply with one word: YES or NO."
)


async def _llm_grade(
    query: str, hits: Sequence[Mapping[str, Any]], force_fast: bool = False
) -> bool:
    """Reproduced live (see docs/TROUBLESHOOTING.md): rewording the reply tokens to
    ANSWERABLE/UNANSWERABLE wasn't enough on its own — DEFAULT_LLM_MODEL (llama3.2:3b) still
    answered the *object-level* question ('no, not without approval') instead of judging
    answerability, for every question whose real answer is restrictive or negative, regardless
    of retrieval quality. qwen2.5:7b-instruct (already the system's designated stronger model —
    see select_primary_model) got every case right in the same live comparison, so this one
    judgment call is worth its extra latency over the default — except on force_fast (the
    post-timeout retry, see docs/DECISIONS.md), which deliberately accepts the weaker signal in
    exchange for the ~20-30s/call this stronger model measured on this project's own 16GB-tier
    hardware, exactly the cost that attempt exists to avoid.

    With the 7B model removed (it did not fit the 16 GB machine) and escalation off, llama3.2:3b
    grades alone, and it replied UNANSWERABLE to every case tried — the vacation question
    with its exact answer in the context included — so the agent retried every question to the
    loop limit. A plain YES/NO question that says a rule or a refusal counts as information
    got 7 of 8 live cases right (the miss: a refusal read as "no information")."""
    if not hits:
        return False
    # Full chunk text, not a slice — see the matching fix in context_utils.py. A 300-char
    # slice here cut off before the sentence that actually answered a live golden question
    # (it only reached the chunk's opening paragraph), so the grading model judged the real,
    # relevant sentence it never saw as absent. See docs/TROUBLESHOOTING.md.
    context = "\n---\n".join(h["text"] for h in hits)
    config = get_model_config()
    grading_model = config.generator if force_fast else config.stronger_model()
    try:
        raw = await complete(
            _GRADE_PROMPT.format(context=context, query=query),
            model=grading_model,
            max_tokens=10,
            temperature=0.0,
        )
        return raw.strip().upper().startswith("YES")
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
            score = best_score
            sufficient = best_score > STRONG_SCORE or (
                best_score > SCORE_THRESHOLD
                and await _llm_grade(state["query"], top, state.get("force_fast", False))
            )
            verdict = "sufficient" if sufficient else "insufficient"
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
    # force_fast (the post-timeout retry attempt — see docs/DECISIONS.md) allows exactly one
    # critic pass, no retries: the point of this attempt is to be fast, not to repeat the same
    # rewrite-and-retry cost that just timed out.
    cap = 1 if state.get("force_fast") else MAX_CRITIC_LOOPS
    if state.get("critic_verdict") == "insufficient" and state.get("loop_count", 0) < cap:
        return "retry"
    return "proceed"
