from __future__ import annotations

from app.graphrag.extractor import Entity
from app.graphrag.resolver import entity_id, normalize_name, resolve_entities


def test_entity_id_is_deterministic_and_label_scoped() -> None:
    id1 = entity_id("PERSON", "Jane Smith")
    id2 = entity_id("PERSON", "  jane   smith ")
    id3 = entity_id("ORG", "Jane Smith")
    assert id1 == id2  # normalization makes these the same
    assert id1 != id3  # different label -> different entity, even with the same name


def test_normalize_name_collapses_whitespace_and_case() -> None:
    assert normalize_name("  Jane   SMITH  ") == "jane smith"


def test_resolve_entities_merges_near_duplicate_mentions() -> None:
    entities = [
        Entity(text="Jane Smith", label="PERSON", start=0, end=10),
        Entity(text="Jane  Smith", label="PERSON", start=20, end=31),  # near-identical
        Entity(text="Acme Corp", label="ORG", start=40, end=49),
    ]
    resolved = resolve_entities(entities)
    person_clusters = [r for r in resolved if r.label == "PERSON"]
    org_clusters = [r for r in resolved if r.label == "ORG"]
    assert len(person_clusters) == 1
    assert set(person_clusters[0].mentions) == {"Jane Smith", "Jane  Smith"}
    assert len(org_clusters) == 1


def test_resolve_entities_does_not_merge_across_labels() -> None:
    entities = [
        Entity(text="Washington", label="PERSON", start=0, end=10),
        Entity(text="Washington", label="GPE", start=20, end=30),
    ]
    resolved = resolve_entities(entities)
    assert len(resolved) == 2
    assert {r.label for r in resolved} == {"PERSON", "GPE"}


def test_resolve_entities_empty_input() -> None:
    assert resolve_entities([]) == []
