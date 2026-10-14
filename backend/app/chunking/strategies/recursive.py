"""Recursively split on paragraph -> line -> sentence -> word boundaries, then greedily pack
units into chunks up to `size` tokens, carrying `overlap` tokens of trailing context forward.
"""

from __future__ import annotations

import re
import uuid

from app.chunking.base import Chunk
from app.chunking.tokenization import TokenCounter

_SEPARATORS = ["\n\n", "\n", r"(?<=[.!?])\s+", " "]


def _split_recursive(text: str, counter: TokenCounter, size: int, depth: int = 0) -> list[str]:
    if counter.count(text) <= size or depth >= len(_SEPARATORS):
        return [text] if text.strip() else []

    sep = _SEPARATORS[depth]
    pieces = [p for p in re.split(sep, text) if p.strip()] if depth < 2 else text.split(sep)
    if len(pieces) <= 1:
        return _split_recursive(text, counter, size, depth + 1)

    out: list[str] = []
    for piece in pieces:
        if counter.count(piece) > size:
            out.extend(_split_recursive(piece, counter, size, depth + 1))
        else:
            out.append(piece)
    return out


class RecursiveChunker:
    name = "recursive"

    def __init__(self, size: int = 512, overlap: int = 64, model_name: str | None = None):
        if overlap >= size:
            raise ValueError("overlap must be smaller than size")
        self.size = size
        self.overlap = overlap
        self._counter = TokenCounter(model_name)

    def chunk(self, doc_id: str, text: str) -> list[Chunk]:
        if not text.strip():
            return []
        units = _split_recursive(text, self._counter, self.size)

        chunks: list[Chunk] = []
        current: list[str] = []
        current_tokens = 0

        def _flush() -> None:
            if not current:
                return
            chunk_text = "\n\n".join(current).strip()
            if not chunk_text:
                return
            c = Chunk(
                chunk_id=str(uuid.uuid4()),
                doc_id=doc_id,
                text=chunk_text,
                token_count=self._counter.count(chunk_text),
                strategy=self.name,
            )
            c.finalize_pii_count()
            chunks.append(c)

        for unit in units:
            unit_tokens = self._counter.count(unit)
            if current and current_tokens + unit_tokens > self.size:
                _flush()
                # Carry the trailing ~overlap tokens of the previous chunk forward.
                overlap_text = self._counter.tail(current[-1], self.overlap)
                current = [overlap_text] if overlap_text.strip() else []
                current_tokens = self._counter.count(overlap_text) if current else 0
            current.append(unit)
            current_tokens += unit_tokens
        _flush()
        return chunks
