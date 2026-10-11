from __future__ import annotations

from app.graphrag.extractor import _parse_triples, extract_entities, extract_triples_llm


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


def test_parse_triples_accepts_a_clean_json_array() -> None:
    raw = '[{"subject": "Marie Curie", "predicate": "discovered", "object": "radium"}]'
    triples = _parse_triples(raw)
    assert len(triples) == 1
    assert triples[0].subject == "Marie Curie"
    assert triples[0].predicate == "discovered"
    assert triples[0].object == "radium"


def test_parse_triples_extracts_json_wrapped_in_prose_and_markdown_fences() -> None:
    raw = (
        "Sure, here are the triples:\n```json\n"
        '[{"subject": "A", "predicate": "relates to", "object": "B"}]\n'
        "```\nLet me know if you need more."
    )
    triples = _parse_triples(raw)
    assert len(triples) == 1
    assert triples[0].subject == "A"


def test_parse_triples_skips_items_missing_a_required_key() -> None:
    raw = (
        '[{"subject": "A", "predicate": "relates to", "object": "B"}, '
        '{"subject": "C", "predicate": "missing object"}]'
    )
    triples = _parse_triples(raw)
    assert len(triples) == 1
    assert triples[0].subject == "A"


def test_parse_triples_skips_non_dict_items() -> None:
    raw = '["just a string", 42, {"subject": "A", "predicate": "relates to", "object": "B"}]'
    triples = _parse_triples(raw)
    assert len(triples) == 1


def test_parse_triples_returns_empty_for_a_non_list_json_value() -> None:
    assert _parse_triples('{"not": "a list"}') == []


def test_parse_triples_returns_empty_for_unparseable_garbage() -> None:
    assert _parse_triples("not json at all, just prose with no brackets") == []


def test_parse_triples_returns_empty_for_an_empty_array() -> None:
    assert _parse_triples("[]") == []


async def test_extract_triples_llm_real_call() -> None:
    text = "Marie Curie discovered radium. Marie Curie won the Nobel Prize in Physics."
    triples = await extract_triples_llm(text, model="ollama/llama3.2:3b", max_triples=5)
    assert isinstance(triples, list)
    if triples:  # the LLM's exact output isn't guaranteed, but if it returned anything...
        assert all(t.subject and t.predicate and t.object for t in triples)


async def test_extract_triples_llm_falls_back_to_empty_list_when_unavailable() -> None:
    triples = await extract_triples_llm("Some text.", model="ollama/this-model-does-not-exist:0b")
    assert triples == []
