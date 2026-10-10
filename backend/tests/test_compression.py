from __future__ import annotations

from app.chunking.tokenization import TokenCounter
from app.retrieval.compression import compress_hits
from app.retrieval.hybrid import FusedHit


def test_compression_respects_token_budget_and_keeps_relevant_sentence() -> None:
    long_text = (
        "The company was founded in 1998 in a small garage. "
        "It has grown steadily every year since. "
        "Employees accrue two paid vacation days for every month worked. "
        "The headquarters moved to a larger building in 2015. "
        "The cafeteria serves lunch every day at noon. "
        "The logo was redesigned twice over the company's history."
    )
    hit = FusedHit(chunk_id="c1", score=0.9, text=long_text)
    counter = TokenCounter()
    full_tokens = counter.count(long_text)
    budget = max(full_tokens // 3, 20)

    compressed = compress_hits("How much vacation do employees get?", [hit], max_tokens=budget)
    assert len(compressed) == 1
    assert counter.count(compressed[0].text) <= budget + 10
    assert "vacation" in compressed[0].text.lower()


def test_compression_leaves_short_text_untouched() -> None:
    hit = FusedHit(chunk_id="c1", score=0.9, text="A short chunk.")
    compressed = compress_hits("anything", [hit], max_tokens=1000)
    assert compressed[0].text == "A short chunk."


def test_compression_handles_empty_hits() -> None:
    assert compress_hits("query", [], max_tokens=100) == []
