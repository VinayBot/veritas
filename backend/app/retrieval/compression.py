"""Context compression: keep only the most query-relevant sentences from each hit, within a
token budget — extractive. There's no LLM-orchestration layer yet to delegate abstractive
summarization to (that's Phase 6's agent pipeline), so this is a deliberately simple, real
mechanism rather than a stub pretending to compress.
"""

from __future__ import annotations

import numpy as np

from app.chunking.strategies._sentences import split_sentences
from app.chunking.tokenization import TokenCounter
from app.embeddings.registry import get_embedder
from app.retrieval.hybrid import FusedHit


def compress_hits(
    query: str, hits: list[FusedHit], max_tokens: int, model_name: str | None = None
) -> list[FusedHit]:
    if not hits:
        return []
    counter = TokenCounter(model_name)
    embedder = get_embedder(model_name)
    query_emb = embedder.embed_one(query)

    budget_per_hit = max(max_tokens // len(hits), 20)
    compressed: list[FusedHit] = []
    for hit in hits:
        if counter.count(hit.text) <= budget_per_hit:
            compressed.append(hit)
            continue

        sentences = split_sentences(hit.text)
        if len(sentences) <= 1:
            compressed.append(hit)
            continue

        sentence_embeddings = embedder.embed(sentences)
        similarities = sentence_embeddings @ query_emb
        order = np.argsort(-similarities)

        kept_indices: list[int] = []
        token_total = 0
        for idx in order:
            idx = int(idx)
            tokens = counter.count(sentences[idx])
            if kept_indices and token_total + tokens > budget_per_hit:
                continue
            kept_indices.append(idx)
            token_total += tokens
            if token_total >= budget_per_hit:
                break

        kept_indices.sort()  # restore original reading order
        new_text = " ".join(sentences[i] for i in kept_indices)
        compressed.append(hit.model_copy(update={"text": new_text}))
    return compressed
