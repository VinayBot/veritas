from __future__ import annotations

from fastapi import APIRouter

from app.api.schemas.graph import GraphResponse
from app.graphrag.service import graph_query
from app.stores.graph.networkx_store import get_graph_store

router = APIRouter(tags=["graph"])


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
