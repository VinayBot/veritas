"""BM25 index over all persisted chunks (app/chunking/models.py: ChunkRow).

bm25s has no incremental-add API, so this rebuilds the whole index from the chunks table after
each ingestion. Fine at demo scale (hundreds-to-low-thousands of chunks); a real deployment
would move to an incremental or sharded index — noted here rather than pretended away.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from app.chunking.models import ChunkRow
from app.core.db import session_scope


@dataclass
class Bm25Hit:
    chunk_id: str
    score: float
    text: str


class Bm25Index:
    def __init__(self) -> None:
        self._retriever = None
        self._chunk_ids: list[str] = []
        self._texts: list[str] = []
        self._doc_ids: list[str] = []
        self._variants: list[str] = []

    def is_empty(self) -> bool:
        return not self._chunk_ids

    def size(self) -> int:
        return len(self._chunk_ids)

    def rebuild(
        self,
        chunk_ids: list[str],
        texts: list[str],
        doc_ids: list[str],
        variants: list[str] | None = None,
    ) -> None:
        import bm25s

        self._chunk_ids = chunk_ids
        self._texts = texts
        self._doc_ids = doc_ids
        self._variants = variants if variants is not None else ["default"] * len(chunk_ids)
        if not texts:
            self._retriever = None
            return
        tokenized = bm25s.tokenize(texts, stopwords="en", show_progress=False)
        retriever = bm25s.BM25()
        retriever.index(tokenized, show_progress=False)
        self._retriever = retriever

    def search(
        self, query: str, k: int, doc_id: str | None = None, variant: str = "default"
    ) -> list[Bm25Hit]:
        import bm25s

        if self._retriever is None or not self._chunk_ids:
            return []
        query_tokens = bm25s.tokenize([query], stopwords="en", show_progress=False)
        # bm25s has no metadata filter, so document and variant are filtered after the fact,
        # which means scoring everything first.
        fetch_k = len(self._chunk_ids)
        indices, scores = self._retriever.retrieve(query_tokens, k=fetch_k, show_progress=False)
        hits = []
        for idx, score in zip(indices[0], scores[0], strict=True):
            if doc_id and self._doc_ids[idx] != doc_id:
                continue
            if self._variants[idx] != variant:
                continue
            hits.append(
                Bm25Hit(chunk_id=self._chunk_ids[idx], score=float(score), text=self._texts[idx])
            )
            if len(hits) >= k:
                break
        return hits


_index = Bm25Index()


def get_bm25_index() -> Bm25Index:
    return _index


async def rebuild_bm25_index() -> None:
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(ChunkRow.chunk_id, ChunkRow.text, ChunkRow.doc_id, ChunkRow.variant)
            )
        ).all()
    _index.rebuild(
        [r[0] for r in rows],
        [r[1] for r in rows],
        [r[2] for r in rows],
        [r[3] or "default" for r in rows],
    )
