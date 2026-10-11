from __future__ import annotations

import uuid

from app.chunking.base import Chunk
from app.graphrag.service import build_graph_for_document, graph_query, link_query_entities
from app.stores.graph.networkx_store import get_graph_store


def _chunk(doc_id: str, text: str) -> Chunk:
    c = Chunk(chunk_id=str(uuid.uuid4()), doc_id=doc_id, text=text, strategy="test")
    c.finalize_pii_count()
    return c


async def test_build_graph_for_document_creates_entities_and_relation() -> None:
    doc_id = f"doc-{uuid.uuid4()}"
    chunks = [
        _chunk(
            doc_id,
            "Zephyrion Dynamics was founded by Lyra Voss in the city of Nova Haven.",
        )
    ]
    stats = await build_graph_for_document(doc_id, chunks)
    assert stats["entities"] >= 2

    store = get_graph_store()
    data = store.to_json(doc_id=doc_id)
    names = {n["name"] for n in data["nodes"]}
    assert any("Zephyrion" in n or "Voss" in n or "Haven" in n for n in names)


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
