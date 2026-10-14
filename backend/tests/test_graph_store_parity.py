"""One set of expectations for both knowledge-graph stores. NetworkX always runs; Neo4j runs
whenever NEO4J_URI points at a reachable server (CI starts one as a service container) and is
skipped with the reason otherwise."""

from __future__ import annotations

import os

import pytest

from app.stores.graph.networkx_store import NetworkXGraphStore, get_graph_store


def _neo4j_store():
    if not os.environ.get("NEO4J_URI"):
        pytest.skip("NEO4J_URI is not set; no Neo4j server to test against")
    neo4j = pytest.importorskip("neo4j")
    from app.stores.graph.neo4j_store import Neo4jGraphStore

    store = Neo4jGraphStore()
    try:
        store._driver.verify_connectivity()
    except neo4j.exceptions.ServiceUnavailable as exc:
        pytest.skip(f"Neo4j at {os.environ['NEO4J_URI']} is not reachable: {exc}")
    store.clear()
    return store


@pytest.fixture(params=["networkx", "neo4j"])
def store(request, tmp_path):
    if request.param == "networkx":
        yield NetworkXGraphStore(path=tmp_path / "graph.pickle")
        return
    neo = _neo4j_store()
    yield neo
    neo.clear()
    neo.close()


def _build(store) -> None:
    """Two documents sharing one entity, a two-hop chain in doc-1, one relation from doc-2."""
    store.upsert_entity("ada", "PERSON", "Ada Lovelace", doc_id="doc-1", mentions=["Ada"])
    store.upsert_entity("engine", "ORG", "Analytical Engine", doc_id="doc-1", mentions=[])
    store.upsert_entity("babbage", "PERSON", "Charles Babbage", doc_id="doc-1", mentions=[])
    store.upsert_entity("ada", "PERSON", "Ada Lovelace", doc_id="doc-2", mentions=["Lovelace"])
    store.upsert_entity("notes", "WORK", "Sketch Notes", doc_id="doc-2", mentions=[])
    store.add_relation("ada", "engine", "wrote about", doc_id="doc-1", chunk_id="c1")
    store.add_relation("engine", "babbage", "designed by", doc_id="doc-1", chunk_id="c2")
    store.add_relation("ada", "notes", "published", doc_id="doc-2", chunk_id="c3")
    store.add_relation("ada", "missing", "ignored", doc_id="doc-1", chunk_id="c4")
    store.save()


def test_entities_merge_across_documents(store) -> None:
    _build(store)
    nodes = {n["id"]: n for n in store.to_json()["nodes"]}
    assert set(nodes) == {"ada", "engine", "babbage", "notes"}
    assert set(nodes["ada"]["doc_ids"]) == {"doc-1", "doc-2"}
    assert {"Ada", "Lovelace"} <= set(nodes["ada"]["mentions"])
    assert store.node_count() == 4
    assert store.edge_count() == 3  # the relation to a missing entity was not added


def test_a_question_links_to_the_entities_it_names(store) -> None:
    _build(store)
    linked = store.find_entities_by_name("What did Ada Lovelace write about?", 5)
    assert [n.id for n in linked] == ["ada"]
    assert store.find_entities_by_name("Who wrote Sketch Notes?", 5, doc_id="doc-1") == []


def test_traversal_follows_relations_in_both_directions_up_to_the_hop_limit(store) -> None:
    _build(store)
    one_hop = store.traverse(["engine"], hops=1)
    assert set(one_hop.nodes) == {"engine", "ada", "babbage"}
    two_hops = store.traverse(["babbage"], hops=2)
    assert {"babbage", "engine", "ada"} <= set(two_hops.nodes)
    assert {(e.source, e.target, e.predicate) for e in two_hops.edges} >= {
        ("engine", "babbage", "designed by"),
        ("ada", "engine", "wrote about"),
    }
    assert store.traverse(["nobody"], hops=2).nodes == []


def test_a_documents_graph_excludes_relations_read_from_another(store) -> None:
    _build(store)
    doc1 = store.to_json(doc_id="doc-1")
    assert {(e["source"], e["target"]) for e in doc1["edges"]} == {
        ("ada", "engine"),
        ("engine", "babbage"),
    }


def test_removing_a_documents_relations_keeps_shared_entities(store) -> None:
    _build(store)
    assert store.remove_doc_edges("doc-1") == 2
    assert store.edge_count() == 1
    assert store.node_count() == 4


def test_communities_group_connected_entities(store) -> None:
    _build(store)
    communities = store.detect_communities()
    assert set(communities) == {"ada", "engine", "babbage", "notes"}


def test_the_factory_honours_graph_store(monkeypatch) -> None:
    from app.core.config import get_settings

    get_graph_store.cache_clear()
    monkeypatch.setattr(get_settings(), "graph_store", "networkx")
    assert isinstance(get_graph_store(), NetworkXGraphStore)
    get_graph_store.cache_clear()
