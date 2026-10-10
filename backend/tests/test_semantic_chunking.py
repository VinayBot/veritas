from __future__ import annotations

from app.chunking.strategies.semantic import SemanticChunker

TOPIC_A = (
    "The quarterly financial report shows revenue growth of twelve percent. "
    "Profit margins improved due to lower manufacturing costs. "
    "The finance team expects this trend to continue next quarter."
)
TOPIC_B = (
    "The new hiking trail opens next spring in the national park. "
    "Visitors can expect scenic mountain views along the route. "
    "Rangers recommend bringing water and sturdy boots."
)


def test_semantic_chunker_splits_at_topic_shift() -> None:
    chunker = SemanticChunker(threshold=0.6, max_size=512)
    chunks = chunker.chunk("doc-1", f"{TOPIC_A}\n\n{TOPIC_B}")
    assert len(chunks) >= 2
    texts = [c.text for c in chunks]
    assert any("revenue" in t.lower() for t in texts)
    assert any("hiking" in t.lower() or "trail" in t.lower() for t in texts)
    # The two topics should land in *different* chunks, not merged into one.
    assert not any("revenue" in t.lower() and "hiking" in t.lower() for t in texts)


def test_semantic_chunker_keeps_related_sentences_together() -> None:
    chunker = SemanticChunker(threshold=0.1, max_size=512)  # low threshold -> rarely splits
    chunks = chunker.chunk("doc-1", TOPIC_A)
    assert len(chunks) == 1
    assert chunks[0].strategy == "semantic"


def test_semantic_chunker_caps_oversized_groups_via_fallback() -> None:
    long_single_topic = " ".join([TOPIC_A] * 40)
    chunker = SemanticChunker(threshold=0.0, max_size=48)  # threshold 0 -> never splits on its own
    chunks = chunker.chunk("doc-1", long_single_topic)
    assert len(chunks) > 1
    assert all(c.token_count <= 48 + 8 for c in chunks)


def test_semantic_chunker_empty_text() -> None:
    chunker = SemanticChunker()
    assert chunker.chunk("doc-1", "") == []


def test_semantic_chunker_single_sentence() -> None:
    chunker = SemanticChunker()
    chunks = chunker.chunk("doc-1", "Just one sentence here.")
    assert len(chunks) == 1
