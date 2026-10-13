"""NetworkX MultiDiGraph — the default graph store. Persisted to a pickle file under
settings.data_dir so it survives server restarts (there's no separate graph database running).
Behind the GraphStore interface so Neo4j (app/stores/graph/neo4j_store.py) is a drop-in swap.
"""

from __future__ import annotations

import pickle
from functools import lru_cache
from pathlib import Path
from typing import Any

import networkx as nx

from app.core.config import get_settings
from app.stores.graph.base import GraphEdge, GraphNode, TraversalPath


class NetworkXGraphStore:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (get_settings().data_dir / "graph.pickle")
        self._graph: nx.MultiDiGraph = self._load()

    def _load(self) -> nx.MultiDiGraph:
        if self._path.exists():
            try:
                with self._path.open("rb") as fh:
                    graph = pickle.load(fh)  # noqa: S301 — our own file, not user input
                if isinstance(graph, nx.MultiDiGraph):
                    return graph
            except (pickle.PickleError, EOFError, OSError):
                pass
        return nx.MultiDiGraph()

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("wb") as fh:
            pickle.dump(self._graph, fh)

    def upsert_entity(
        self, node_id: str, label: str, name: str, doc_id: str, mentions: list[str]
    ) -> None:
        if self._graph.has_node(node_id):
            node = self._graph.nodes[node_id]
            doc_ids = set(node.get("doc_ids", []))
            doc_ids.add(doc_id)
            node["doc_ids"] = sorted(doc_ids)
            existing_mentions = set(node.get("mentions", []))
            existing_mentions.update(mentions)
            node["mentions"] = sorted(existing_mentions)
        else:
            self._graph.add_node(
                node_id,
                label=label,
                name=name,
                doc_ids=[doc_id],
                mentions=sorted(set(mentions)) or [name],
                community=None,
            )

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        predicate: str,
        doc_id: str | None = None,
        chunk_id: str | None = None,
    ) -> None:
        if not self._graph.has_node(source_id) or not self._graph.has_node(target_id):
            return
        self._graph.add_edge(
            source_id, target_id, predicate=predicate, doc_id=doc_id, chunk_id=chunk_id
        )

    def find_entities_by_name(self, query_text: str, limit: int = 5) -> list[GraphNode]:
        from rapidfuzz import fuzz, process

        if self._graph.number_of_nodes() == 0:
            return []
        # A one- or two-character name ("1", "US") partially matches almost any query.
        names = {
            n: name
            for n in self._graph.nodes
            if len(name := str(self._graph.nodes[n].get("name", n))) >= 3
        }
        if not names:
            return []
        matches = process.extract(
            query_text, names, scorer=fuzz.partial_ratio, limit=limit, score_cutoff=60
        )
        return [self._to_node(node_id) for _, _score, node_id in matches]

    def _to_node(self, node_id: str) -> GraphNode:
        data = self._graph.nodes[node_id]
        return GraphNode(
            id=node_id,
            label=data.get("label", "UNKNOWN"),
            name=data.get("name", node_id),
            doc_ids=data.get("doc_ids", []),
            mentions=data.get("mentions", []),
            community=data.get("community"),
        )

    def traverse(self, start_ids: list[str], hops: int) -> TraversalPath:
        visited: set[str] = set()
        frontier = [n for n in start_ids if self._graph.has_node(n)]
        visited.update(frontier)
        edges: list[GraphEdge] = []

        for _ in range(max(hops, 0)):
            next_frontier: list[str] = []
            for node_id in frontier:
                for _, target, data in self._graph.out_edges(node_id, data=True):
                    edges.append(
                        GraphEdge(
                            source=node_id,
                            target=target,
                            predicate=data.get("predicate", "related_to"),
                            doc_id=data.get("doc_id"),
                            chunk_id=data.get("chunk_id"),
                        )
                    )
                    if target not in visited:
                        visited.add(target)
                        next_frontier.append(target)
                for source, _, data in self._graph.in_edges(node_id, data=True):
                    edges.append(
                        GraphEdge(
                            source=source,
                            target=node_id,
                            predicate=data.get("predicate", "related_to"),
                            doc_id=data.get("doc_id"),
                            chunk_id=data.get("chunk_id"),
                        )
                    )
                    if source not in visited:
                        visited.add(source)
                        next_frontier.append(source)
            frontier = next_frontier
            if not frontier:
                break

        return TraversalPath(nodes=sorted(visited), edges=edges)

    def detect_communities(self) -> dict[str, int]:
        if self._graph.number_of_nodes() == 0:
            return {}
        undirected = self._graph.to_undirected()
        communities = nx.algorithms.community.louvain_communities(undirected, seed=42)
        assignment: dict[str, int] = {}
        for idx, community in enumerate(communities):
            for node_id in community:
                assignment[node_id] = idx
                self._graph.nodes[node_id]["community"] = idx
        return assignment

    def to_json(self, doc_id: str | None = None) -> dict[str, Any]:
        if doc_id is None:
            node_ids = set(self._graph.nodes)
        else:
            node_ids = {
                n for n in self._graph.nodes if doc_id in self._graph.nodes[n].get("doc_ids", [])
            }
        nodes = [self._to_node(n).model_dump() for n in node_ids]
        edges = [
            {
                "source": u,
                "target": v,
                "predicate": data.get("predicate"),
                "doc_id": data.get("doc_id"),
                "chunk_id": data.get("chunk_id"),
            }
            for u, v, data in self._graph.edges(data=True)
            if u in node_ids
            and v in node_ids
            # Entities are shared across documents, so two of this document's entities can
            # also be linked by a relation read from a different one. That relation is not
            # part of this document's graph.
            and (doc_id is None or data.get("doc_id") in (None, doc_id))
        ]
        return {"nodes": nodes, "edges": edges}

    def remove_doc_edges(self, doc_id: str) -> int:
        """Drops relations tagged with this doc_id — used before a re-chunk (Phase 8 advisor
        'accept') so stale edges don't keep pointing at chunk_ids that no longer exist. Entity
        *nodes* are left alone: they're keyed by resolved name, not chunk, and may still be
        mentioned by other documents."""
        stale = [
            (u, v, k)
            for u, v, k, data in self._graph.edges(keys=True, data=True)
            if data.get("doc_id") == doc_id
        ]
        self._graph.remove_edges_from(stale)
        return len(stale)

    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    def edge_count(self) -> int:
        return self._graph.number_of_edges()


@lru_cache(maxsize=1)
def get_graph_store() -> NetworkXGraphStore:
    return NetworkXGraphStore()
