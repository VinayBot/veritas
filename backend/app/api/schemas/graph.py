from __future__ import annotations

from pydantic import BaseModel


class GraphNodeOut(BaseModel):
    id: str
    label: str
    name: str
    doc_ids: list[str]
    mentions: list[str]
    community: int | None = None


class GraphEdgeOut(BaseModel):
    source: str
    target: str
    predicate: str | None = None
    doc_id: str | None = None
    chunk_id: str | None = None


class GraphResponse(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]
    linked_entities: list[GraphNodeOut] | None = None
