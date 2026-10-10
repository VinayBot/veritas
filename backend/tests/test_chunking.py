from __future__ import annotations

from app.chunking.registry import get_baseline_chunker, get_chunker, supported_strategies
from app.chunking.strategies.fixed import FixedChunker
from app.chunking.strategies.parent_child import ParentChildChunker
from app.chunking.strategies.recursive import RecursiveChunker
from app.chunking.strategies.sentence_window import SentenceWindowChunker
from app.chunking.strategies.structure_aware import StructureAwareChunker

LONG_TEXT = " ".join(
    f"This is sentence number {i} in a reasonably long synthetic document used for testing."
    for i in range(200)
)


def test_fixed_chunker_respects_size_and_overlap() -> None:
    chunker = FixedChunker(size=64, overlap=8)
    chunks = chunker.chunk("doc-1", LONG_TEXT)
    assert len(chunks) > 1
    for c in chunks:
        assert c.token_count <= 64
        assert c.doc_id == "doc-1"
        assert c.strategy == "fixed"


def test_fixed_chunker_empty_text() -> None:
    assert FixedChunker().chunk("doc-1", "   ") == []


def test_recursive_chunker_merges_small_units_and_caps_large_ones() -> None:
    chunker = RecursiveChunker(size=64, overlap=8)
    chunks = chunker.chunk("doc-1", LONG_TEXT)
    assert len(chunks) > 1
    for c in chunks:
        assert c.token_count <= 64 + 16  # small slack for the overlap carry-forward


def test_recursive_chunker_single_short_text_is_one_chunk() -> None:
    chunker = RecursiveChunker(size=512, overlap=64)
    chunks = chunker.chunk("doc-1", "A short paragraph with just one idea in it.")
    assert len(chunks) == 1


def test_sentence_window_chunker_overlaps_by_stride() -> None:
    chunker = SentenceWindowChunker(window=4, stride=2)
    text = ". ".join(f"Sentence {i}" for i in range(20)) + "."
    chunks = chunker.chunk("doc-1", text)
    assert len(chunks) > 1
    assert all("core_sentence" in c.extra for c in chunks)


def test_structure_aware_chunker_tracks_section_path() -> None:
    text = (
        "# Title\n\nIntro paragraph.\n\n"
        "## Section A\n\nContent of section A.\n\n"
        "## Section B\n\nContent of section B.\n"
    )
    chunker = StructureAwareChunker(size=512, overlap=0)
    chunks = chunker.chunk("doc-1", text)
    paths = {c.section_path for c in chunks}
    assert "Title > Section A" in paths
    assert "Title > Section B" in paths


def test_structure_aware_chunker_falls_back_for_oversized_section() -> None:
    text = "# Title\n\n" + LONG_TEXT
    chunker = StructureAwareChunker(size=64, overlap=8)
    chunks = chunker.chunk("doc-1", text)
    assert len(chunks) > 1
    assert all(c.section_path == "Title" for c in chunks)


def test_parent_child_chunker_links_children_to_parent() -> None:
    chunker = ParentChildChunker(parent_size=96, parent_overlap=8, child_size=24, child_overlap=4)
    chunks = chunker.chunk("doc-1", LONG_TEXT)
    parents = [c for c in chunks if c.extra.get("role") == "parent"]
    children = [c for c in chunks if c.extra.get("role") == "child"]
    assert parents and children
    parent_ids = {p.chunk_id for p in parents}
    assert all(c.parent_id in parent_ids for c in children)


def test_registry_lists_all_strategies_and_builds_baseline() -> None:
    strategies = supported_strategies()
    for name in (
        "fixed",
        "recursive",
        "sentence_window",
        "semantic",
        "structure_aware",
        "parent_child",
    ):
        assert name in strategies
    baseline = get_baseline_chunker()
    assert baseline.name == "recursive"
    assert get_chunker("fixed", size=128, overlap=16).name == "fixed"
