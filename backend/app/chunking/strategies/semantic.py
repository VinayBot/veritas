"""Embedding-similarity breakpoints: embed each sentence, insert a chunk boundary wherever
consecutive-sentence cosine similarity drops below `threshold`, then cap any resulting group
that's still too large with the recursive splitter.
"""

from __future__ import annotations

import uuid

import numpy as np

from app.chunking.base import Chunk
from app.chunking.strategies._sentences import split_sentences
from app.chunking.strategies.recursive import RecursiveChunker
from app.chunking.tokenization import TokenCounter
from app.embeddings.registry import Embedder, get_embedder


class SemanticChunker:
    name = "semantic"

    def __init__(
        self,
        threshold: float = 0.5,
        max_size: int = 512,
        embedder: Embedder | None = None,
        model_name: str | None = None,
    ):
        self.threshold = threshold
        self.max_size = max_size
        self._embedder = embedder or get_embedder(model_name)
        self._counter = TokenCounter(model_name)
        self._fallback = RecursiveChunker(size=max_size, overlap=0, model_name=model_name)

    def chunk(self, doc_id: str, text: str) -> list[Chunk]:
        sentences = split_sentences(text)
        if not sentences:
            return []
        if len(sentences) == 1:
            groups = [sentences]
        else:
            embeddings = self._embedder.embed(sentences)
            sims = np.sum(embeddings[:-1] * embeddings[1:], axis=1)  # already L2-normalized

            groups = [[sentences[0]]]
            for i, sim in enumerate(sims):
                if sim < self.threshold:
                    groups.append([])
                groups[-1].append(sentences[i + 1])

        chunks: list[Chunk] = []
        for group in groups:
            group_text = " ".join(group)
            if self._counter.count(group_text) <= self.max_size:
                c = Chunk(
                    chunk_id=str(uuid.uuid4()),
                    doc_id=doc_id,
                    text=group_text,
                    token_count=self._counter.count(group_text),
                    strategy=self.name,
                )
                c.finalize_pii_count()
                chunks.append(c)
            else:
                for sub in self._fallback.chunk(doc_id, group_text):
                    sub.strategy = self.name
                    chunks.append(sub)
        return chunks
