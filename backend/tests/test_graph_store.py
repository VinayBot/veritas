from __future__ import annotations

from app.stores.graph.networkx_store import NetworkXGraphStore


def test_upsert_and_relation_round_trip(tmp_path) -> None:
    store = NetworkXGraphStore(path=tmp_path / "graph.pickle")
    store.upsert_entity("e1", "PERSON", "Ada Lovelace", doc_id="doc-1", mentions=["Ada Lovelace"])
    store.upsert_entity("e2", "ORG", "Analytical Engine Co", doc_id="doc-1", mentions=["AEC"])
    store.add_relation("e1", "e2", "founded", doc_id="doc-1", chunk_id="c1")

    data = store.to_json()
    node_ids = {n["id"] for n in data["nodes"]}
    assert {"e1", "e2"} <= node_ids
    assert any(e["source"] == "e1" and e["target"] == "e2" for e in data["edges"])


def test_upsert_merges_doc_ids_and_mentions_on_second_call(tmp_path) -> None:
    store = NetworkXGraphStore(path=tmp_path / "graph.pickle")
    store.upsert_entity("e1", "PERSON", "Ada Lovelace", doc_id="doc-1", mentions=["Ada"])
    store.upsert_entity("e1", "PERSON", "Ada Lovelace", doc_id="doc-2", mentions=["Lovelace"])

    data = store.to_json()
    node = next(n for n in data["nodes"] if n["id"] == "e1")
    assert set(node["doc_ids"]) == {"doc-1", "doc-2"}
    assert set(node["mentions"]) == {"Ada", "Lovelace"}


def test_relation_to_nonexistent_node_is_a_noop(tmp_path) -> None:
    store = NetworkXGraphStore(path=tmp_path / "graph.pickle")
    store.upsert_entity("e1", "PERSON", "Ada", doc_id="doc-1", mentions=["Ada"])
    store.add_relation("e1", "does-not-exist", "related_to")  # must not raise
    assert store.edge_count() == 0


def test_traverse_two_hops(tmp_path) -> None:
    store = NetworkXGraphStore(path=tmp_path / "graph.pickle")
    for i in range(4):
        store.upsert_entity(f"n{i}", "ORG", f"Org{i}", doc_id="doc-1", mentions=[f"Org{i}"])
    store.add_relation("n0", "n1", "connected_to", doc_id="doc-1")
    store.add_relation("n1", "n2", "connected_to", doc_id="doc-1")
    store.add_relation("n2", "n3", "connected_to", doc_id="doc-1")

    one_hop = store.traverse(["n0"], hops=1)
    assert set(one_hop.nodes) == {"n0", "n1"}

    two_hop = store.traverse(["n0"], hops=2)
    assert set(two_hop.nodes) == {"n0", "n1", "n2"}


def test_detect_communities_groups_connected_components(tmp_path) -> None:
    store = NetworkXGraphStore(path=tmp_path / "graph.pickle")
    for name in ("a1", "a2", "b1", "b2"):
        store.upsert_entity(name, "ORG", name, doc_id="doc-1", mentions=[name])
    store.add_relation("a1", "a2", "related_to")
    store.add_relation("b1", "b2", "related_to")

    assignment = store.detect_communities()
    assert assignment["a1"] == assignment["a2"]
    assert assignment["b1"] == assignment["b2"]
    assert assignment["a1"] != assignment["b1"]


def test_find_entities_by_name_fuzzy_match(tmp_path) -> None:
    store = NetworkXGraphStore(path=tmp_path / "graph.pickle")
    store.upsert_entity("e1", "ORG", "Globex Corporation", doc_id="doc-1", mentions=["Globex"])
    matches = store.find_entities_by_name("Globex", limit=3)
    assert any(m.id == "e1" for m in matches)


def test_save_and_reload_round_trip(tmp_path) -> None:
    path = tmp_path / "graph.pickle"
    store = NetworkXGraphStore(path=path)
    store.upsert_entity("e1", "PERSON", "Grace Hopper", doc_id="doc-1", mentions=["Grace Hopper"])
    store.save()

    reloaded = NetworkXGraphStore(path=path)
    assert reloaded.node_count() == 1
    assert reloaded.to_json()["nodes"][0]["name"] == "Grace Hopper"


def test_to_json_filters_by_doc_id(tmp_path) -> None:
    store = NetworkXGraphStore(path=tmp_path / "graph.pickle")
    store.upsert_entity("e1", "ORG", "DocA Corp", doc_id="doc-a", mentions=["DocA Corp"])
    store.upsert_entity("e2", "ORG", "DocB Corp", doc_id="doc-b", mentions=["DocB Corp"])

    scoped = store.to_json(doc_id="doc-a")
    ids = {n["id"] for n in scoped["nodes"]}
    assert ids == {"e1"}


def test_remove_doc_edges_drops_only_that_docs_relations(tmp_path) -> None:
    store = NetworkXGraphStore(path=tmp_path / "graph.pickle")
    store.upsert_entity("e1", "ORG", "Acme", doc_id="doc-a", mentions=["Acme"])
    store.upsert_entity("e2", "ORG", "Globex", doc_id="doc-a", mentions=["Globex"])
    store.upsert_entity("e3", "ORG", "Initech", doc_id="doc-b", mentions=["Initech"])
    store.add_relation("e1", "e2", "partnered_with", doc_id="doc-a", chunk_id="old-chunk-1")
    store.add_relation("e2", "e3", "partnered_with", doc_id="doc-b", chunk_id="chunk-b1")

    removed = store.remove_doc_edges("doc-a")
    assert removed == 1
    assert store.edge_count() == 1

    data = store.to_json()
    # entity nodes survive — only the doc-a-tagged relation is gone, chunk-b1's edge is intact.
    assert {"e1", "e2", "e3"} <= {n["id"] for n in data["nodes"]}
    assert all(e["doc_id"] != "doc-a" for e in data["edges"])
    assert any(e["chunk_id"] == "chunk-b1" for e in data["edges"])

    # idempotent — calling it again with nothing left to remove is a no-op, not an error.
    assert store.remove_doc_edges("doc-a") == 0
