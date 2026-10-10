"""Cross-encoder reranking: a (query, chunk) pair scored jointly by one model is more accurate
than comparing two independently-embedded vectors — too slow to run over a whole corpus, which
is exactly why it only reranks the top-N hybrid candidates rather than replacing dense search.
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.retrieval.hybrid import FusedHit


class CrossEncoderReranker:
    def __init__(self, model_name: str | None = None):
        from sentence_transformers import CrossEncoder

        self.model_name = model_name or get_settings().reranker_model
        self._model = CrossEncoder(self.model_name)

    def rerank(self, query: str, hits: list[FusedHit]) -> list[FusedHit]:
        if not hits:
            return []
        pairs = [(query, h.text) for h in hits]
        scores = self._model.predict(pairs)
        rescored = [
            hit.model_copy(update={"rerank_score": float(score)})
            for hit, score in zip(hits, scores, strict=True)
        ]
        rescored.sort(key=lambda h: h.rerank_score or 0.0, reverse=True)
        return rescored


@lru_cache(maxsize=2)
def get_reranker(model_name: str | None = None) -> CrossEncoderReranker:
    return CrossEncoderReranker(model_name)
