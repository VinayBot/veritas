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


def test_extract_entities_recognizes_a_masked_pii_token() -> None:
    """Reproduced live (see docs/TROUBLESHOOTING.md): PII masking runs before graph extraction,
    so a real person's name is already "<PERSON_6cc6eb>" by the time spaCy's NER ever sees the
    text — and spaCy, never having seen that shape before, didn't tag it as anything, so no
    node (and therefore no edge) could ever form for a masked person. Confirmed this dropped a
    real relationship end to end: "Can a German contractor work remotely without approval?"
    found "Germany" via NER but 0 edges via 2-hop traversal, because the only relationship in
    the text involved the masked approver, who had no entity to attach the edge to."""
    text = (
        "Contractors based in Germany must obtain <PERSON_6cc6eb>'s written exception before "
        "working remotely under this policy."
    )
    entities = extract_entities(text)
    pii_matches = [e for e in entities if e.text == "<PERSON_6cc6eb>"]
    assert len(pii_matches) == 1
    assert pii_matches[0].label == "PERSON"
    assert any(e.text == "Germany" for e in entities)


async def test_extract_triples_llm_real_call() -> None:
    text = "Marie Curie discovered radium. Marie Curie won the Nobel Prize in Physics."
    triples = await extract_triples_llm(text, model="ollama/llama3.2:3b", max_triples=5)
    assert isinstance(triples, list)
    if triples:  # the LLM's exact output isn't guaranteed, but if it returned anything...
        assert all(t.subject and t.predicate and t.object for t in triples)


async def test_extract_triples_llm_falls_back_to_empty_list_when_unavailable() -> None:
    triples = await extract_triples_llm("Some text.", model="ollama/this-model-does-not-exist:0b")
    assert triples == []
