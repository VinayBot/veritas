"""Query Rewriter: HyDE, step-back, and multi-query-expansion are three different retrieval
tricks, not three things to run on every call — each critic retry loop tries a *different* one
(first HyDE, then step-back, then multi-query) rather than paying for all three upfront. This
also makes "rewrite and retry" (Section 8.C) a real retry of a different strategy, not the same
one repeated.
"""

from __future__ import annotations

import logging

from app.agents.state import AgentState, record_step
from app.core.tracing import trace_bus
from app.llm.client import LlmUnavailableError, complete
from app.retrieval.hyde import hyde_rewrite

logger = logging.getLogger(__name__)

_STEP_BACK_PROMPT = (
    "Given this specific question, write one more general question whose answer would provide "
    "useful background context. Reply with only the question, nothing else.\n\nQuestion: {query}"
)
_MULTI_QUERY_PROMPT = (
    "Rewrite this question as a short search query using different but related wording. Reply "
    "with only the rewritten query, nothing else.\n\nQuestion: {query}"
)


async def _llm_rewrite(prompt_template: str, query: str) -> str:
    try:
        result = await complete(
            prompt_template.format(query=query), max_tokens=100, temperature=0.3
        )
        return result.strip() or query
    except LlmUnavailableError:
        return query


async def rewriter_node(state: AgentState) -> dict:
    loop = state.get("loop_count", 0)
    query = state["query"]

    async with trace_bus.stage(
        state["session_id"], "rewriter", from_stage="planner", to_stage="retriever"
    ) as h:
        if loop == 0:
            technique = "hyde"
            search_text = await hyde_rewrite(query)
        elif loop == 1:
            technique = "step_back"
            search_text = await _llm_rewrite(_STEP_BACK_PROMPT, query)
        else:
            technique = "multi_query"
            search_text = await _llm_rewrite(_MULTI_QUERY_PROMPT, query)
        h.set_metric("technique", technique)
        h.set_output(f"[{technique}] {search_text[:120]}")

    summary = f"Rewrote the query using {technique.replace('_', ' ')}."
    return {
        "search_text": search_text,
        "agent_steps": record_step(state, "rewriter", summary),
    }
