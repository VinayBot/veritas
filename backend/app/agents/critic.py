"""Critic (corrective RAG): grades retrieved context on two independent signals — the
cross-encoder relevance score already attached by the Retriever's hybrid_search tool, and a
direct LLM yes/no judgment — and decides whether to retry with a different rewrite technique.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.agents.state import MAX_CRITIC_LOOPS, AgentState, record_step
from app.core.tracing import trace_bus
from app.llm.client import LlmUnavailableError, complete

SCORE_THRESHOLD = 0.3

_GRADE_PROMPT = (
    "Context:\n{context}\n\nQuestion: {query}\n\n"
    "Can this question be answered using ONLY the context above? Reply with exactly one word: "
    "yes or no."
)


async def _llm_grade(query: str, hits: Sequence[Mapping[str, Any]]) -> bool:
    if not hits:
        return False
    context = "\n---\n".join(h["text"][:300] for h in hits)
    try:
        raw = await complete(
            _GRADE_PROMPT.format(context=context, query=query), max_tokens=10, temperature=0.0
        )
        return raw.strip().lower().startswith("yes")
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
            avg_score = sum(r["score"] for r in top) / len(top)
            llm_says_yes = await _llm_grade(state["query"], top)
            score = avg_score
            verdict = (
                "sufficient" if (avg_score > SCORE_THRESHOLD and llm_says_yes) else "insufficient"
            )
        h.set_metric("avg_score", score)
        h.set_metric("verdict", verdict)
        h.set_metric("loop_count", loop_count)
        h.set_output(f"verdict={verdict} avg_score={score:.3f}")

    summary = f"Judged evidence as {verdict} (avg relevance {score:.2f})."
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
