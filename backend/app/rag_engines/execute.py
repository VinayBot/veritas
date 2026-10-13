"""Runs the retrieval half of a direct strategy by calling the existing building blocks with
the arguments its plan declares."""

from __future__ import annotations

from app.agents.tools import graph_traverse_tool, hit_to_dict
from app.rag_engines.base import StrategySpec
from app.retrieval import service as retrieval_service

# How many graph-only chunks may be added on top of the ranked search results.
GRAPH_EXTRA = 3


async def retrieve(spec: StrategySpec, query: str, document_id: str | None) -> list[dict]:
    plan = spec.plan
    if plan is None:
        raise ValueError(f"{spec.id} is not a direct strategy; it has no retrieval plan")

    hits = [
        hit_to_dict(h)
        for h in await retrieval_service.search(
            query,
            k=plan.k,
            doc_id=document_id,
            mode=plan.mode,
            use_hyde=plan.hyde,
            rerank=plan.rerank,
            dedupe_strategy=plan.dedupe,
            variant=plan.variant,
        )
    ]
    if not plan.graph:
        return hits

    # Graph traversal contributes the chunks that relations lead to. Ones the ranked search
    # already found are marked as found both ways; new ones are appended after them.
    by_id = {h["chunk_id"]: h for h in hits}
    added = 0
    for graph_hit in await graph_traverse_tool(query, doc_id=document_id):
        existing = by_id.get(graph_hit["chunk_id"])
        if existing is not None:
            existing["found_by"] = f"{existing['found_by']}+graph"
        elif added < GRAPH_EXTRA:
            hits.append(graph_hit)
            by_id[graph_hit["chunk_id"]] = graph_hit
            added += 1
    return hits
