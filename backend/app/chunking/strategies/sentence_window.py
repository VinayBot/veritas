"""Each chunk is a sliding window of `window` sentences, stepping `stride` sentences at a time
(stride < window gives overlap) — the core sentence index is kept in `extra` so retrieval can
later highlight just the core sentence within its window of context.
"""

from __future__ import annotations

import uuid

from app.chunking.base import Chunk
from app.chunking.strategies._sentences import split_sentences
from app.chunking.tokenization import TokenCounter


class SentenceWindowChunker:
    name = "sentence_window"

    def __init__(self, window: int = 5, stride: int = 3, model_name: str | None = None):
        if stride <= 0 or stride > window:
            raise ValueError("stride must be in (0, window]")
        self.window = window
        self.stride = stride
        self._counter = TokenCounter(model_name)

    def chunk(self, doc_id: str, text: str) -> list[Chunk]:
        sentences = split_sentences(text)
        if not sentences:
            return []

        chunks: list[Chunk] = []
        start = 0
        while start < len(sentences):
            window_sentences = sentences[start : start + self.window]
            core_index = min(self.stride // 2, len(window_sentences) - 1)
            chunk_text = " ".join(window_sentences)
            c = Chunk(
                chunk_id=str(uuid.uuid4()),
                doc_id=doc_id,
                text=chunk_text,
                token_count=self._counter.count(chunk_text),
                strategy=self.name,
                extra={
                    "core_sentence": window_sentences[core_index],
                    "window_start_sentence": start,
                },
            )
            c.finalize_pii_count()
            chunks.append(c)
            if start + self.window >= len(sentences):
                break
            start += self.stride
        return chunks
