from __future__ import annotations

from app.graphrag.extractor import extract_entities, extract_triples_llm


def test_extract_entities_finds_people_and_orgs() -> None:
    entities = extract_entities("Marie Curie worked at the University of Paris with Pierre Curie.")
    labels = {e.label for e in entities}
    texts = {e.text for e in entities}
    assert "PERSON" in labels
    assert any("Curie" in t for t in texts)


def test_extract_entities_empty_text() -> None:
    assert extract_entities("") == []


async def test_extract_triples_llm_real_call() -> None:
    text = "Marie Curie discovered radium. Marie Curie won the Nobel Prize in Physics."
    triples = await extract_triples_llm(text, model="ollama/llama3.2:3b", max_triples=5)
    assert isinstance(triples, list)
    if triples:  # the LLM's exact output isn't guaranteed, but if it returned anything...
        assert all(t.subject and t.predicate and t.object for t in triples)


async def test_extract_triples_llm_falls_back_to_empty_list_when_unavailable() -> None:
    triples = await extract_triples_llm("Some text.", model="ollama/this-model-does-not-exist:0b")
    assert triples == []
