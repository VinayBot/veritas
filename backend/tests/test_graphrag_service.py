from __future__ import annotations

import uuid

import pytest

from app.chunking.base import Chunk
from app.graphrag.service import build_graph_for_document, graph_query, link_query_entities
from app.stores.graph.networkx_store import get_graph_store


def _chunk(doc_id: str, text: str) -> Chunk:
    c = Chunk(chunk_id=str(uuid.uuid4()), doc_id=doc_id, text=text, strategy="test")
    c.finalize_pii_count()
    return c


@pytest.mark.needs_ollama
async def test_build_graph_for_document_creates_entities_and_relation() -> None:
    """Despite its name, this previously only ever asserted on entity count — stats["triples"]
    and the actual edges were never checked, so a regression that broke relation extraction/
    linking entirely (e.g. the Bug G-style exact-match linking failure in build_graph_for_
    document) would have passed this test silently. Confirmed live and deterministic
    (temperature=0.0, identical across 3 runs) before asserting on it strictly."""
    doc_id = f"doc-{uuid.uuid4()}"
    chunks = [
        _chunk(
            doc_id,
            "Zephyrion Dynamics was founded by Lyra Voss in the city of Nova Haven.",
        )
    ]
    stats = await build_graph_for_document(doc_id, chunks)
    assert stats["entities"] >= 2
    assert stats["triples"] >= 1

    store = get_graph_store()
    data = store.to_json(doc_id=doc_id)
    names = {n["name"] for n in data["nodes"]}
    assert any("Zephyrion" in n or "Voss" in n or "Haven" in n for n in names)
    assert len(data["edges"]) >= 1
    name_by_id = {n["id"]: n["name"] for n in data["nodes"]}
    edge_pairs = {(name_by_id.get(e["source"]), name_by_id.get(e["target"])) for e in data["edges"]}
    assert ("Zephyrion Dynamics", "Lyra Voss") in edge_pairs


async def test_build_graph_creates_a_node_for_a_masked_pii_token() -> None:
    """Reproduced live (see docs/TROUBLESHOOTING.md): before the extractor fix, this exact
    shape of sentence created a node for "Germany" but none for the masked approver, so no
    edge between them was ever possible — graph-mode chat found the "Germany" entity but 0
    edges within 2 hops, for every question whose answer involved a masked person. The node
    count is the deterministic half of the fix (regex-based, not LLM-dependent); whether the
    LLM's triple extraction *also* links them this specific run is the probabilistic half
    already covered by test_build_graph_for_document_creates_entities_and_relation above."""
    doc_id = f"doc-{uuid.uuid4()}"
    chunks = [
        _chunk(
            doc_id,
            "Contractors based in Germany must obtain <PERSON_6cc6eb>'s written exception "
            "before working remotely under this policy.",
        )
    ]
    stats = await build_graph_for_document(doc_id, chunks)
    assert stats["entities"] >= 2

    store = get_graph_store()
    data = store.to_json(doc_id=doc_id)
    names = {n["name"] for n in data["nodes"]}
    assert "<PERSON_6cc6eb>" in names
    assert "Germany" in names


async def test_community_detection_separates_two_unrelated_document_topics() -> None:
    """detect_communities() runs Louvain over one shared cross-document graph (service.py:48),
    not scoped per document — the existing low-level test
    (test_graph_store.py::test_detect_communities_groups_connected_components) only exercises
    the algorithm directly on a hand-built, isolated store. Nothing exercised it via the real
    pipeline (extraction -> linking -> build_graph_for_document) at anything past a trivial
    scale, which is exactly where the real behavior (observed live: ~330 communities, mostly
    singletons, on the actual accumulated dev graph) diverges from the simple hand-built case.
    This proves the real pipeline, given two genuinely unrelated topics, still separates them
    rather than merging everything into one blob — asserted relatively (cluster 1's entities
    land in a different community than cluster 2's), not as an absolute community count, since
    the shared store may carry state from whatever else has run in this process."""
    doc_id_1 = f"doc-{uuid.uuid4()}"
    doc_id_2 = f"doc-{uuid.uuid4()}"
    chunks_1 = [
        _chunk(doc_id_1, "Zephyrion Dynamics was founded by Lyra Voss in the city of Nova Haven.")
    ]
    chunks_2 = [
        _chunk(
            doc_id_2, "Thornwick Bakery was acquired by Petra Mallory in the town of Ashford Vale."
        )
    ]
    await build_graph_for_document(doc_id_1, chunks_1)
    await build_graph_for_document(doc_id_2, chunks_2)

    store = get_graph_store()
    assignment = store.detect_communities()

    data_1 = store.to_json(doc_id=doc_id_1)
    data_2 = store.to_json(doc_id=doc_id_2)
    ids_1 = {n["id"] for n in data_1["nodes"]}
    ids_2 = {n["id"] for n in data_2["nodes"]}
    assert ids_1 and ids_2

    communities_1 = {assignment[i] for i in ids_1 if i in assignment}
    communities_2 = {assignment[i] for i in ids_2 if i in assignment}
    assert communities_1, "cluster 1's entities got no community assignment at all"
    assert communities_2, "cluster 2's entities got no community assignment at all"
    assert communities_1.isdisjoint(communities_2), (
        f"two unrelated topics landed in the same community: {communities_1} & {communities_2}"
    )


async def test_build_graph_skips_chunks_with_too_few_entities() -> None:
    doc_id = f"doc-{uuid.uuid4()}"
    chunks = [_chunk(doc_id, "ok.")]  # no real entities at all
    stats = await build_graph_for_document(doc_id, chunks)
    assert stats["entities"] == 0
    assert stats["triples"] == 0


async def test_link_query_entities_finds_known_entity() -> None:
    doc_id = f"doc-{uuid.uuid4()}"
    chunks = [_chunk(doc_id, "Quendrith Holdings announced a merger with Brakmoor Industries.")]
    await build_graph_for_document(doc_id, chunks)

    linked = link_query_entities("Quendrith")
    assert any("Quendrith" in n.name for n in linked)


async def test_graph_query_returns_empty_for_unknown_entity() -> None:
    result = graph_query("ThisEntityDefinitelyDoesNotExistAnywhere123")
    assert result["nodes"] == []
    assert result["edges"] == []
    assert result["linked_entities"] == []


async def test_relations_between_concepts_become_graph_nodes(monkeypatch) -> None:
    """A technical passage names few entities NER recognises; the relations a model reads out
    of it still belong in the graph, as concept nodes. Clause-length "subjects" and numbers
    do not."""
    from app.graphrag import service
    from app.graphrag.extractor import Triple

    async def fake_triples(text, model=None, max_triples=8):  # noqa: ANN001, ARG001
        return [
            Triple(subject="dialog manager", predicate="decides", object="response message"),
            Triple(
                subject="the part of the system that the user never actually gets to see at all",
                predicate="is",
                object="backend",
            ),
        ]

    monkeypatch.setattr(service, "extract_triples_llm", fake_triples)
    doc_id = f"doc-{uuid.uuid4()}"
    text = (
        "The dialog manager decides which response message is sent back. It costs 12 dollars. " * 4
    )
    stats = await build_graph_for_document(doc_id, [_chunk(doc_id, text)])
    data = get_graph_store().to_json(doc_id=doc_id)
    names = {n["name"] for n in data["nodes"]}
    assert {"dialog manager", "response message"} <= names
    assert not any(len(name.split()) > 6 for name in names)
    assert not any(n["label"] in {"CARDINAL", "MONEY"} for n in data["nodes"])
    assert stats["triples"] == 1 and stats["concepts"] == 2
    assert len(data["edges"]) == 1
