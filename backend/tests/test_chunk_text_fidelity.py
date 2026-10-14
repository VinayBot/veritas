"""Chunk text is the document's own text. A tokenizer round-trip lowercased and re-spaced it
("<PERSON_b43251>" became "< person _ b43251 >"), which the benchmark's PII scan then reported
as a leaked name and which reached the model and the citations in that form."""

from __future__ import annotations

import re

from app.chunking.strategies.fixed import FixedChunker
from app.chunking.strategies.recursive import RecursiveChunker
from app.chunking.tokenization import TokenCounter

TEXT = "\n\n".join(
    f"Section {i}. Approval for Trip-{i} comes from <PERSON_b43251> at Northwind (ext. 4{i}). "
    "Receipts are filed within 30 days; late claims need the CFO's sign-off."
    for i in range(40)
)
MASK = re.compile(r"<[A-Z][A-Z_]*_[0-9a-f]{6,}>")


def _assert_faithful(chunks) -> None:
    assert len(chunks) > 1
    for chunk in chunks:
        for piece in chunk.text.split("\n\n"):
            assert piece.strip() in TEXT, piece[:80]
        assert "< person" not in chunk.text  # the decoded, broken form of a mask token
        for fragment in re.findall(r"<[^>]*>?", chunk.text):
            assert MASK.fullmatch(fragment), fragment


def test_recursive_chunks_and_their_overlap_keep_the_original_text() -> None:
    _assert_faithful(RecursiveChunker(size=128, overlap=32).chunk("d", TEXT))


def test_fixed_windows_are_cut_from_the_original_text() -> None:
    chunks = FixedChunker(size=96, overlap=16).chunk("d", TEXT)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.text in TEXT
        for fragment in re.findall(r"<[^>]*>?", chunk.text):
            assert MASK.fullmatch(fragment), fragment


def test_a_tail_never_starts_inside_a_mask_token() -> None:
    counter = TokenCounter()
    text = "Ask <PERSON_b43251> today"
    for n in range(1, counter.count(text) + 1):
        tail = counter.tail(text, n)
        assert text.endswith(tail)
        assert "PERSON_b43251>" not in tail or "<PERSON_b43251>" in tail
