"""Relations that need no language model: named entities in the same sentence are linked, for
every chunk, so the graph stays connected where the model had no time (or no availability)
to read typed relations."""

from __future__ import annotations

import uuid

from app.chunking.base import Chunk
from app.graphrag.resolver import normalize_name, resolve_entities
from app.graphrag.service import CO_OCCURRENCE_PREDICATE, _add_co_occurrences, graph_entities
from app.stores.graph.networkx_store import NetworkXGraphStore


def _ingest(store, text: str) -> str:
    doc_id = str(uuid.uuid4())
    chunk = Chunk(
        chunk_id=str(uuid.uuid4()), doc_id=doc_id, text=text, token_count=0, strategy="recursive"
    )
    entities = graph_entities(text)
    mention_to_id = {}
    for r in resolve_entities(entities):
        store.upsert_entity(r.id, r.label, r.canonical_name, doc_id=doc_id, mentions=r.mentions)
        for mention in r.mentions:
            mention_to_id[normalize_name(mention)] = r.id
    _add_co_occurrences(store, doc_id, chunk, entities, mention_to_id)
    return doc_id


def test_entities_in_one_sentence_are_linked_and_across_sentences_are_not(tmp_path) -> None:
    store = NetworkXGraphStore(path=tmp_path / "g.pickle")
    _ingest(
        store,
        "Microsoft opened an office in Lisbon. Google expanded in Nairobi.",
    )
    edges = {
        frozenset((e["source"], e["target"]))
        for e in store.to_json()["edges"]
        if e["predicate"] == CO_OCCURRENCE_PREDICATE
    }
    names = {n["id"]: n["name"] for n in store.to_json()["nodes"]}
    pairs = {frozenset(names[i] for i in edge) for edge in edges}
    assert frozenset({"Microsoft", "Lisbon"}) in pairs
    assert frozenset({"Google", "Nairobi"}) in pairs
    assert frozenset({"Microsoft", "Nairobi"}) not in pairs


def test_a_long_list_of_names_does_not_become_a_clique(tmp_path) -> None:
    store = NetworkXGraphStore(path=tmp_path / "g.pickle")
    cities = ["Lisbon", "Madrid", "Paris", "Berlin", "Rome", "Vienna", "Prague", "Warsaw", "Oslo"]
    _ingest(store, "Offices: " + ", ".join(cities) + ".")
    assert store.edge_count() <= 15  # at most 6 entities per sentence: 6 * 5 / 2 pairs
