"""Small-to-big: large parent chunks for context, small child chunks (linked via parent_id)
for embedding/search. Retrieval (Phase 4) searches children and expands to the parent for the
LLM's context — this strategy only has to produce the linked structure.
"""

from __future__ import annotations

from app.chunking.base import Chunk
from app.chunking.strategies.recursive import RecursiveChunker


class ParentChildChunker:
    name = "parent_child"

    def __init__(
        self,
        parent_size: int = 1024,
        parent_overlap: int = 100,
        child_size: int = 256,
        child_overlap: int = 32,
        model_name: str | None = None,
    ):
        self._parent_chunker = RecursiveChunker(
            size=parent_size, overlap=parent_overlap, model_name=model_name
        )
        self._child_chunker = RecursiveChunker(
            size=child_size, overlap=child_overlap, model_name=model_name
        )

    def chunk(self, doc_id: str, text: str) -> list[Chunk]:
        parents = self._parent_chunker.chunk(doc_id, text)
        out: list[Chunk] = []
        for parent in parents:
            parent.strategy = self.name
            parent.extra["role"] = "parent"
            out.append(parent)

            children = self._child_chunker.chunk(doc_id, parent.text)
            for child in children:
                child.parent_id = parent.chunk_id
                child.strategy = self.name
                child.extra["role"] = "child"
                out.append(child)
        return out
