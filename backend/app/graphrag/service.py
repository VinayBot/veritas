"""Orchestrates GraphRAG end to end: `build_graph_for_document` runs at ingestion (per Section
8.B); `graph_query` does query-time entity linking + hop traversal for Graph RAG mode and the
Phase 6 agentic `graph_traverse` tool.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable

from app.chunking.base import Chunk
from app.graphrag.extractor import extract_entities, extract_triples_llm
from app.graphrag.resolver import normalize_name, resolve_entities
from app.stores.graph.base import GraphNode
from app.stores.graph.networkx_store import get_graph_store

# Typed relations are read by a model, one call per chunk, so only the chunks richest in
# entities are sent, and the whole pass stops at a time budget. Entities come from fast local
# NER and always cover every chunk, and so do co-occurrence relations (below).
MAX_TRIPLE_CHUNKS = 20
TRIPLE_TIME_BUDGET_SECONDS = 240.0

# Two named entities in the same sentence are related, even when the model reads nothing
# more specific: every chunk gets these, so a long document's graph is not limited to the
# chunks the model had time to read. Capped per sentence so a list of names does not become
# a clique.
CO_OCCURRENCE_PREDICATE = "mentioned with"
MAX_ENTITIES_PER_SENTENCE = 6
_SENTENCE_RE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")

# Numbers, amounts and dates are not things a document is "about": as graph nodes they become
# hubs like "annually" or "1" that link unrelated passages and match any query containing a
# digit. They stay out of the graph (the profiler still counts them).
NON_ENTITY_LABELS = frozenset(
    {"CARDINAL", "ORDINAL", "QUANTITY", "PERCENT", "MONEY", "DATE", "TIME"}
)
MIN_ENTITY_NAME_LENGTH = 3


def graph_entities(text: str) -> list:
    return [
        e
        for e in extract_entities(text)
        if e.label not in NON_ENTITY_LABELS and len(e.text.strip()) >= MIN_ENTITY_NAME_LENGTH
    ]


MIN_CHUNK_CHARS_FOR_TRIPLES = 200
CONCEPT_PREFIX = "concept:"
MAX_CONCEPT_WORDS = 6


def _node_for(store, doc_id: str, name: str, mention_to_id: dict[str, str]) -> str | None:  # noqa: ANN001
    """The graph node a relation's subject or object refers to. A named entity the NER pass
    found is reused. Anything else the model read out of the passage ("dialog manager",
    "semantic analysis") becomes a concept node — unless it is a whole clause rather than a
    thing, which is dropped."""
    key = normalize_name(name)
    if key in mention_to_id:
        return mention_to_id[key]
    words = key.split()
    if len(key) < MIN_ENTITY_NAME_LENGTH or not words or len(words) > MAX_CONCEPT_WORDS:
        return None
    node_id = f"{CONCEPT_PREFIX}{key}"
    store.upsert_entity(node_id, "CONCEPT", name.strip(), doc_id=doc_id, mentions=[name.strip()])
    return node_id


def _add_co_occurrences(
    store, doc_id: str, chunk: Chunk, entities: list, mention_to_id: dict
) -> int:  # noqa: ANN001
    added = 0
    seen: set[tuple[str, str]] = set()
    for sentence in _SENTENCE_RE.finditer(chunk.text):
        ids: list[str] = []
        for ent in entities:
            if sentence.start() <= ent.start and ent.end <= sentence.end():
                node = mention_to_id.get(normalize_name(ent.text))
                if node and node not in ids:
                    ids.append(node)
        ids = ids[:MAX_ENTITIES_PER_SENTENCE]
        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                pair = (min(a, b), max(a, b))
                if pair in seen:
                    continue
                seen.add(pair)
                store.add_relation(
                    pair[0],
                    pair[1],
                    CO_OCCURRENCE_PREDICATE,
                    doc_id=doc_id,
                    chunk_id=chunk.chunk_id,
                )
                added += 1
    return added


GraphProgress = Callable[[float, str], Awaitable[None]]


async def build_graph_for_document(
    doc_id: str, chunks: list[Chunk], progress: GraphProgress | None = None
) -> dict:
    """Two passes. Entities first, for every chunk, saved straight away — so the graph exists
    even if relation extraction is slow or interrupted. Then relations for the most
    entity-dense chunks, saved after each one."""
    store = get_graph_store()
    store.remove_doc_edges(doc_id)  # a rebuild replaces this document's relations
    total_entities = 0
    total_triples = 0
    total_co = 0
    named: dict[str, dict[str, str]] = {}

    for chunk in chunks:
        entities = graph_entities(chunk.text)
        if not entities:
            continue
        resolved = resolve_entities(entities)
        mention_to_id: dict[str, str] = {}
        for r in resolved:
            store.upsert_entity(r.id, r.label, r.canonical_name, doc_id=doc_id, mentions=r.mentions)
            for mention in r.mentions:
                mention_to_id[normalize_name(mention)] = r.id
            total_entities += 1
        named[chunk.chunk_id] = mention_to_id
        total_co += _add_co_occurrences(store, doc_id, chunk, entities, mention_to_id)
    # Every chunk with real text is a candidate for relation reading, richest in named
    # entities first: a technical document has few named entities but plenty of relations
    # between its concepts.
    candidates = [
        (len(named.get(chunk.chunk_id, {})), chunk, named.get(chunk.chunk_id, {}))
        for chunk in chunks
        if len(chunk.text.strip()) >= MIN_CHUNK_CHARS_FOR_TRIPLES
        or len(named.get(chunk.chunk_id, {})) >= 2
    ]
    store.detect_communities()
    store.save()

    candidates.sort(key=lambda c: (-c[0], -len(c[1].text)))
    selected = candidates[:MAX_TRIPLE_CHUNKS]
    started = time.monotonic()
    read = 0
    concepts: set[str] = set()
    for index, (_, chunk, mention_to_id) in enumerate(selected):
        if time.monotonic() - started > TRIPLE_TIME_BUDGET_SECONDS:
            break
        if progress is not None:
            await progress(
                index / len(selected), f"Reading relations: chunk {index + 1} of {len(selected)}"
            )
        triples = await extract_triples_llm(chunk.text)
        read += 1
        for triple in triples:
            source_id = _node_for(store, doc_id, triple.subject, mention_to_id)
            target_id = _node_for(store, doc_id, triple.object, mention_to_id)
            if source_id is None or target_id is None or source_id == target_id:
                continue
            if source_id.startswith(CONCEPT_PREFIX):
                concepts.add(source_id)
            if target_id.startswith(CONCEPT_PREFIX):
                concepts.add(target_id)
            store.add_relation(
                source_id, target_id, triple.predicate, doc_id=doc_id, chunk_id=chunk.chunk_id
            )
            total_triples += 1
        store.save()

    communities = store.detect_communities()
    store.save()
    return {
        "entities": total_entities + len(concepts),
        "named_entities": total_entities,
        "concepts": len(concepts),
        "triples": total_triples,
        "co_occurrences": total_co,
        "communities": len(set(communities.values())),
        "chunks": len(chunks),
        "chunks_read_for_relations": read,
        "chunks_with_relations_skipped": len(candidates) - read,
    }


def link_query_entities(query: str, limit: int = 5, doc_id: str | None = None) -> list[GraphNode]:
    store = get_graph_store()
    direct = store.find_entities_by_name(query, limit=limit, doc_id=doc_id)
    if direct:
        return direct

    found: list[GraphNode] = []
    for ent in extract_entities(query):
        found.extend(store.find_entities_by_name(ent.text, limit=2, doc_id=doc_id))
    seen: set[str] = set()
    out: list[GraphNode] = []
    for node in found:
        if node.id not in seen:
            seen.add(node.id)
            out.append(node)
    return out[:limit]


def graph_query(query: str, hops: int = 2, doc_id: str | None = None) -> dict:
    """Entities the query mentions and what is reachable from them. With `doc_id`, both the
    entities and the relations followed belong to that document."""
    store = get_graph_store()
    linked = link_query_entities(query, doc_id=doc_id)
    if not linked:
        return {"linked_entities": [], "nodes": [], "edges": []}
    path = store.traverse([n.id for n in linked], hops=hops)
    edges = [e.model_dump() for e in path.edges if doc_id is None or e.doc_id in (None, doc_id)]
    if doc_id is None:
        nodes = path.nodes
    else:
        reached = (
            {n.id for n in linked} | {e["source"] for e in edges} | {e["target"] for e in edges}
        )
        nodes = [n for n in path.nodes if n in reached]
    return {
        "linked_entities": [n.model_dump() for n in linked],
        "nodes": nodes,
        "edges": edges,
    }
