"""Neo4j adapter behind the same (synchronous) GraphStore interface as NetworkXGraphStore —
enabled by the `neo4j` Docker Compose profile (`docker compose --profile neo4j up`). Uses
neo4j's sync driver, not the async one, specifically so it matches NetworkXGraphStore's sync
methods and the two are truly interchangeable behind one Protocol.

Community detection has no bundled Louvain here (that needs the separate GDS plugin, not
guaranteed present), so it pulls the graph into memory and runs the same networkx Louvain the
default store uses — Neo4j is just the store, not where the algorithm runs.
"""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.stores.graph.base import GraphEdge, GraphNode, TraversalPath


class Neo4jGraphStore:
    def __init__(self) -> None:
        from neo4j import GraphDatabase

        settings = get_settings()
        self._driver = GraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )

    def close(self) -> None:
        self._driver.close()

    def save(self) -> None:
        """Every write is already committed in its own transaction; nothing to flush. Present
        so callers can treat both stores alike."""

    def clear(self) -> None:
        with self._driver.session() as session:
            session.run("MATCH (n:Entity) DETACH DELETE n")

    def upsert_entity(
        self, node_id: str, label: str, name: str, doc_id: str, mentions: list[str]
    ) -> None:
        def _tx(tx: Any) -> None:
            record = tx.run(
                "MATCH (n:Entity {id: $id}) RETURN n.doc_ids AS doc_ids, n.mentions AS mentions",
                id=node_id,
            ).single()
            if record:
                doc_ids = set(record["doc_ids"] or []) | {doc_id}
                all_mentions = set(record["mentions"] or []) | set(mentions)
            else:
                doc_ids = {doc_id}
                all_mentions = set(mentions) or {name}
            tx.run(
                "MERGE (n:Entity {id: $id}) "
                "SET n.label = $label, n.name = $name, n.doc_ids = $doc_ids, "
                "    n.mentions = $mentions",
                id=node_id,
                label=label,
                name=name,
                doc_ids=sorted(doc_ids),
                mentions=sorted(all_mentions),
            )

        with self._driver.session() as session:
            session.execute_write(_tx)

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        predicate: str,
        doc_id: str | None = None,
        chunk_id: str | None = None,
    ) -> None:
        with self._driver.session() as session:
            session.run(
                "MATCH (s:Entity {id: $source_id}), (t:Entity {id: $target_id}) "
                # CREATE, like the NetworkX MultiDiGraph: each reading of a relation is its
                # own edge (MERGE on a pattern with a null chunk_id is also an error).
                "CREATE (s)-[r:RELATES {predicate: $predicate, doc_id: $doc_id, "
                "chunk_id: $chunk_id}]->(t)",
                source_id=source_id,
                target_id=target_id,
                predicate=predicate,
                doc_id=doc_id,
                chunk_id=chunk_id,
            )

    def find_entities_by_name(
        self, query_text: str, limit: int = 5, doc_id: str | None = None
    ) -> list[GraphNode]:
        """Same linking as the NetworkX store: the candidate names (this document's, when
        `doc_id` is given) are read once, and the shared fuzzy matcher picks those that appear
        in the question."""
        from app.stores.graph.networkx_store import match_names

        with self._driver.session() as session:
            records = list(
                session.run(
                    "MATCH (n:Entity) WHERE $doc IS NULL OR $doc IN n.doc_ids RETURN n",
                    doc=doc_id,
                )
            )
        by_id = {r["n"]["id"]: r["n"] for r in records}
        names = {node_id: str(data.get("name", node_id)) for node_id, data in by_id.items()}
        return [self._to_node(by_id[node_id]) for node_id in match_names(query_text, names, limit)]

    def _to_node(self, data: Any) -> GraphNode:
        return GraphNode(
            id=data["id"],
            label=data.get("label", "UNKNOWN"),
            name=data.get("name", data["id"]),
            doc_ids=data.get("doc_ids", []),
            mentions=data.get("mentions", []),
            community=data.get("community"),
        )

    def traverse(self, start_ids: list[str], hops: int) -> TraversalPath:
        with self._driver.session() as session:
            result = session.run(
                "MATCH (start:Entity) WHERE start.id IN $start_ids "
                "MATCH path = (start)-[r:RELATES*0.." + str(max(hops, 0)) + "]-(other:Entity) "
                "UNWIND relationships(path) AS rel "
                "RETURN DISTINCT startNode(rel).id AS source, endNode(rel).id AS target, "
                "       rel.predicate AS predicate, rel.doc_id AS doc_id, rel.chunk_id AS chunk_id",
                start_ids=start_ids,
            )
            records = list(result)
        edges = [
            GraphEdge(
                source=r["source"],
                target=r["target"],
                predicate=r["predicate"] or "related_to",
                doc_id=r["doc_id"],
                chunk_id=r["chunk_id"],
            )
            for r in records
        ]
        with self._driver.session() as session:
            existing = {
                r["id"]
                for r in session.run(
                    "MATCH (n:Entity) WHERE n.id IN $ids RETURN n.id AS id", ids=start_ids
                )
            }
        nodes = sorted({e.source for e in edges} | {e.target for e in edges} | existing)
        return TraversalPath(nodes=nodes, edges=edges)

    def detect_communities(self) -> dict[str, int]:
        import networkx as nx

        with self._driver.session() as session:
            node_ids = [r["id"] for r in session.run("MATCH (n:Entity) RETURN n.id AS id")]
            edges = [
                (r["source"], r["target"])
                for r in session.run(
                    "MATCH (s:Entity)-[:RELATES]-(t:Entity) RETURN s.id AS source, t.id AS target"
                )
            ]

        graph = nx.Graph()
        graph.add_nodes_from(node_ids)
        graph.add_edges_from(edges)
        if graph.number_of_nodes() == 0:
            return {}
        communities = nx.algorithms.community.louvain_communities(graph, seed=42)

        assignment: dict[str, int] = {}
        with self._driver.session() as session:
            for idx, community in enumerate(communities):
                for node_id in community:
                    assignment[node_id] = idx
                session.run(
                    "MATCH (n:Entity) WHERE n.id IN $ids SET n.community = $idx",
                    ids=list(community),
                    idx=idx,
                )
        return assignment

    def to_json(self, doc_id: str | None = None) -> dict[str, Any]:
        with self._driver.session() as session:
            if doc_id:
                node_result = session.run(
                    "MATCH (n:Entity) WHERE $doc_id IN n.doc_ids RETURN n", doc_id=doc_id
                )
            else:
                node_result = session.run("MATCH (n:Entity) RETURN n")
            nodes = [self._to_node(r["n"]).model_dump() for r in node_result]
            node_ids = {n["id"] for n in nodes}

            edges = [
                {
                    "source": r["source"],
                    "target": r["target"],
                    "predicate": r["predicate"],
                    "doc_id": r["doc_id"],
                    "chunk_id": r["chunk_id"],
                }
                for r in session.run(
                    "MATCH (s:Entity)-[r:RELATES]->(t:Entity) "
                    "RETURN s.id AS source, t.id AS target, r.predicate AS predicate, "
                    "       r.doc_id AS doc_id, r.chunk_id AS chunk_id"
                )
                if r["source"] in node_ids
                and r["target"] in node_ids
                # As in the NetworkX store: a relation read from another document is not part
                # of this document's graph, even between two of its entities.
                and (doc_id is None or r["doc_id"] in (None, doc_id))
            ]
        return {"nodes": nodes, "edges": edges}

    def remove_doc_edges(self, doc_id: str) -> int:
        with self._driver.session() as session:
            record = session.run(
                "MATCH ()-[r:RELATES {doc_id: $doc_id}]->() DELETE r RETURN count(r) AS n",
                doc_id=doc_id,
            ).single()
        return int(record["n"]) if record else 0

    def node_count(self) -> int:
        with self._driver.session() as session:
            record = session.run("MATCH (n:Entity) RETURN count(n) AS n").single()
        return int(record["n"]) if record else 0

    def edge_count(self) -> int:
        with self._driver.session() as session:
            record = session.run("MATCH ()-[r:RELATES]->() RETURN count(r) AS n").single()
        return int(record["n"]) if record else 0
