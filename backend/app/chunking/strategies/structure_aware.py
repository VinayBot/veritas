"""Splits at Markdown heading boundaries (the structure Docling/trafilatura already preserve),
keeping a breadcrumb `section_path` per chunk. Oversized sections fall back to RecursiveChunker.
"""

from __future__ import annotations

import re
import uuid

from app.chunking.base import Chunk
from app.chunking.strategies.recursive import RecursiveChunker
from app.chunking.tokenization import TokenCounter

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _split_sections(text: str) -> list[tuple[list[str], str]]:
    """Returns [(heading_breadcrumb_parts, section_body)]."""
    sections: list[tuple[list[str], str]] = []
    stack: list[str] = []
    body_lines: list[str] = []

    def _flush() -> None:
        body = "\n".join(body_lines).strip()
        if body:
            sections.append((list(stack), body))
        body_lines.clear()

    for line in text.split("\n"):
        match = _HEADING_RE.match(line.strip())
        if match:
            _flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            stack = stack[: level - 1] + [title]
        else:
            body_lines.append(line)
    _flush()
    return sections


class StructureAwareChunker:
    name = "structure_aware"

    def __init__(self, size: int = 384, overlap: int = 40, model_name: str | None = None):
        self.size = size
        self.overlap = overlap
        self._counter = TokenCounter(model_name)
        self._fallback = RecursiveChunker(size=size, overlap=overlap, model_name=model_name)

    def chunk(self, doc_id: str, text: str) -> list[Chunk]:
        sections = _split_sections(text)
        if not sections:
            return []

        chunks: list[Chunk] = []
        for breadcrumb, body in sections:
            section_path = " > ".join(breadcrumb) if breadcrumb else None
            if self._counter.count(body) <= self.size:
                c = Chunk(
                    chunk_id=str(uuid.uuid4()),
                    doc_id=doc_id,
                    text=body,
                    section_path=section_path,
                    token_count=self._counter.count(body),
                    strategy=self.name,
                )
                c.finalize_pii_count()
                chunks.append(c)
            else:
                for sub in self._fallback.chunk(doc_id, body):
                    sub.section_path = section_path
                    sub.strategy = self.name
                    chunks.append(sub)
        return chunks
