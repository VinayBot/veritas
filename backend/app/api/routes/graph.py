from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import APIRouter

from app.api.schemas.graph import GraphResponse
from app.graphrag.service import graph_query
from app.stores.graph.networkx_store import get_graph_store

router = APIRouter(tags=["graph"])

MAX_OVERVIEW_NODES = 200


def _degrees(data: dict[str, Any]) -> Counter:
    degree: Counter = Counter()
    for edge in data["edges"]:
        degree[edge["source"]] += 1
        degree[edge["target"]] += 1
    return degree


@router.get("/graph/stats")
async def graph_stats(document_id: str | None = None) -> dict:
    """Shape of the knowledge graph, for the whole corpus or one document: how big it is, its
    largest communities, its most connected entities, and what share of entities have no
    relation at all."""
    data = get_graph_store().to_json(doc_id=document_id)
    nodes, edges = data["nodes"], data["edges"]
    degree = _degrees(data)
    by_id = {n["id"]: n for n in nodes}
    communities: dict[int, list[dict]] = {}
    for node in nodes:
        if node.get("community") is not None:
            communities.setdefault(node["community"], []).append(node)
    orphans = sum(1 for n in nodes if degree[n["id"]] == 0)
    largest = sorted(communities.items(), key=lambda kv: -len(kv[1]))[:5]
    return {
        "document_id": document_id,
        "entities": len(nodes),
        "relations": len(edges),
        "communities": len(communities),
        "orphans": orphans,
        "orphan_rate": orphans / len(nodes) if nodes else None,
        "largest_communities": [
            {
                "id": cid,
                "size": len(members),
                "top_entities": [
                    m["name"] for m in sorted(members, key=lambda m: -degree[m["id"]])[:4]
                ],
            }
            for cid, members in largest
        ],
        "most_connected": [
            {
                "id": node_id,
                "name": by_id[node_id]["name"],
                "label": by_id[node_id]["label"],
                "degree": count,
                "doc_ids": by_id[node_id]["doc_ids"],
            }
            for node_id, count in degree.most_common(8)
            if node_id in by_id
        ],
    }


@router.get("/graph", response_model=GraphResponse)
async def get_corpus_graph(limit: int = MAX_OVERVIEW_NODES) -> GraphResponse:
    """The corpus-wide graph, cut to its `limit` most connected entities and the relations
    among them, for an overview that stays drawable."""
    data = get_graph_store().to_json()
    degree = _degrees(data)
    keep = {
        n["id"]
        for n in sorted(data["nodes"], key=lambda n: -degree[n["id"]])[
            : max(1, min(limit, MAX_OVERVIEW_NODES))
        ]
    }
    return GraphResponse(
        nodes=[n for n in data["nodes"] if n["id"] in keep],
        edges=[e for e in data["edges"] if e["source"] in keep and e["target"] in keep],
    )


@router.get("/graph/{document_id}", response_model=GraphResponse)
async def get_graph(document_id: str, query: str | None = None, hops: int = 2) -> GraphResponse:
    if query:
        result = graph_query(query, hops=hops)
        store = get_graph_store()
        full = store.to_json(doc_id=document_id)
        node_by_id = {n["id"]: n for n in full["nodes"]}
        path_nodes = [node_by_id[n] for n in result["nodes"] if n in node_by_id]
        return GraphResponse(
            nodes=path_nodes or full["nodes"],
            edges=result["edges"] or full["edges"],
            linked_entities=result["linked_entities"],
        )

    store = get_graph_store()
    data = store.to_json(doc_id=document_id)
    return GraphResponse(nodes=data["nodes"], edges=data["edges"])
