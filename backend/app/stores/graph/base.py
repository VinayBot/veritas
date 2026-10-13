from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: str
    label: str
    name: str
    doc_ids: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    community: int | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    predicate: str
    doc_id: str | None = None
    chunk_id: str | None = None


class TraversalPath(BaseModel):
    nodes: list[str]
    edges: list[GraphEdge]


class GraphStore(Protocol):
    def upsert_entity(
        self, node_id: str, label: str, name: str, doc_id: str, mentions: list[str]
    ) -> None: ...

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        predicate: str,
        doc_id: str | None = None,
        chunk_id: str | None = None,
    ) -> None: ...

    def find_entities_by_name(
        self, query_text: str, limit: int, doc_id: str | None = None
    ) -> list[GraphNode]: ...

    def traverse(self, start_ids: list[str], hops: int) -> TraversalPath: ...

    def detect_communities(self) -> dict[str, int]: ...

    def to_json(self, doc_id: str | None = None) -> dict[str, Any]: ...

    def remove_doc_edges(self, doc_id: str) -> int: ...
