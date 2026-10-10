"""Orchestrates GraphRAG end to end: `build_graph_for_document` runs at ingestion (per Section
8.B); `graph_query` does query-time entity linking + hop traversal for Graph RAG mode and the
Phase 6 agentic `graph_traverse` tool.
"""

from __future__ import annotations

from app.chunking.base import Chunk
from app.graphrag.extractor import extract_entities, extract_triples_llm
from app.graphrag.resolver import normalize_name, resolve_entities
from app.stores.graph.base import GraphNode
from app.stores.graph.networkx_store import get_graph_store

MIN_ENTITIES_FOR_TRIPLES = 2


async def build_graph_for_document(doc_id: str, chunks: list[Chunk]) -> dict:
    store = get_graph_store()
    total_entities = 0
    total_triples = 0

    for chunk in chunks:
        entities = extract_entities(chunk.text)
        if len(entities) < MIN_ENTITIES_FOR_TRIPLES:
            continue

        resolved = resolve_entities(entities)
        mention_to_id: dict[str, str] = {}
        for r in resolved:
            store.upsert_entity(r.id, r.label, r.canonical_name, doc_id=doc_id, mentions=r.mentions)
            for mention in r.mentions:
                mention_to_id[normalize_name(mention)] = r.id
            total_entities += 1

        triples = await extract_triples_llm(chunk.text)
        for triple in triples:
            source_id = mention_to_id.get(normalize_name(triple.subject))
            target_id = mention_to_id.get(normalize_name(triple.object))
            if source_id is None or target_id is None:
                # Couldn't link the triple's subject/object back to an entity this chunk's NER
                # pass actually found — dropped rather than guessed at.
                continue
            store.add_relation(
                source_id, target_id, triple.predicate, doc_id=doc_id, chunk_id=chunk.chunk_id
            )
            total_triples += 1

    communities = store.detect_communities()
    store.save()
    return {
        "entities": total_entities,
        "triples": total_triples,
        "communities": len(set(communities.values())),
    }


def link_query_entities(query: str, limit: int = 5) -> list[GraphNode]:
    store = get_graph_store()
    direct = store.find_entities_by_name(query, limit=limit)
    if direct:
        return direct

    found: list[GraphNode] = []
    for ent in extract_entities(query):
        found.extend(store.find_entities_by_name(ent.text, limit=2))
    seen: set[str] = set()
    out: list[GraphNode] = []
    for node in found:
        if node.id not in seen:
            seen.add(node.id)
            out.append(node)
    return out[:limit]


def graph_query(query: str, hops: int = 2) -> dict:
    store = get_graph_store()
    linked = link_query_entities(query)
    if not linked:
        return {"linked_entities": [], "nodes": [], "edges": []}
    path = store.traverse([n.id for n in linked], hops=hops)
    return {
        "linked_entities": [n.model_dump() for n in linked],
        "nodes": path.nodes,
        "edges": [e.model_dump() for e in path.edges],
    }
