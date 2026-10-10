"""Retriever: runs whichever tools the Planner selected, once per sub-question, merging and
de-duplicating (by chunk_id, keeping the higher score) into one evidence set for the Critic.
"""

from __future__ import annotations

from app.agents.state import AgentState, record_step
from app.agents.tools import graph_traverse_tool, hybrid_search_tool, pii_vault_lookup_tool
from app.core.tracing import trace_bus
from app.guardrails.retrieval import scan_hits


async def retriever_node(state: AgentState) -> dict:
    tools = state.get("tools") or ["hybrid_search"]
    sub_questions = state.get("sub_questions") or [state["query"]]
    search_text = state.get("search_text") or state["query"]
    doc_id = state.get("document_id")

    all_hits: dict[str, dict] = {}

    async with trace_bus.stage(
        state["session_id"], "retriever", from_stage="rewriter", to_stage="critic"
    ) as h:
        if "pii_vault_lookup" in tools:
            for hit in await pii_vault_lookup_tool(
                state["query"], state["session_id"], state.get("reveal_pii", False)
            ):
                all_hits[hit["chunk_id"]] = hit

        if "hybrid_search" in tools:
            for sub_q in sub_questions:
                # Only the primary query gets the rewriter's HyDE/step-back/multi-query text —
                # sub-questions from decomposition are searched as-is.
                text = search_text if sub_q == state["query"] else sub_q
                for hit in await hybrid_search_tool(text, doc_id, k=5):
                    existing = all_hits.get(hit["chunk_id"])
                    if existing is None or hit["score"] > existing["score"]:
                        all_hits[hit["chunk_id"]] = hit

        if "graph_traverse" in tools:
            for sub_q in sub_questions:
                for hit in await graph_traverse_tool(sub_q):
                    all_hits.setdefault(hit["chunk_id"], hit)

        merged = sorted(all_hits.values(), key=lambda h: h["score"], reverse=True)[:10]
        merged = await scan_hits(merged, state["session_id"], h.trace_id)
        h.set_metric("hit_count", len(merged))
        h.set_metric("flagged_count", sum(1 for hit in merged if hit.get("flagged_injection")))
        h.set_metric("tools_used", tools)
        h.set_output(f"{len(merged)} chunks via {tools}")

    summary = f"Retrieved {len(merged)} piece(s) of evidence using {', '.join(tools)}."
    return {"retrieved": merged, "agent_steps": record_step(state, "retriever", summary)}
