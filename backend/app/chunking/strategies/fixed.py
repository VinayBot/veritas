"""Fixed-size token windows with overlap — the baseline strategy (512 tokens / 64 overlap)."""

from __future__ import annotations

import uuid

from app.chunking.base import Chunk
from app.chunking.tokenization import TokenCounter


class FixedChunker:
    name = "fixed"

    def __init__(self, size: int = 512, overlap: int = 64, model_name: str | None = None):
        if overlap >= size:
            raise ValueError("overlap must be smaller than size")
        self.size = size
        self.overlap = overlap
        self._counter = TokenCounter(model_name)

    def chunk(self, doc_id: str, text: str) -> list[Chunk]:
        if not text.strip():
            return []
        ids = self._counter.encode(text)
        if not ids:
            return []

        chunks: list[Chunk] = []
        step = self.size - self.overlap
        start = 0
        while start < len(ids):
            window = ids[start : start + self.size]
            chunk_text = self._counter.decode(window)
            chunk = Chunk(
                chunk_id=str(uuid.uuid4()),
                doc_id=doc_id,
                text=chunk_text,
                token_count=len(window),
                strategy=self.name,
                extra={"start_token": start},
            )
            chunk.finalize_pii_count()
            chunks.append(chunk)
            if start + self.size >= len(ids):
                break
            start += step
        return chunks
