"""Cross-encoder reranking: a (query, chunk) pair scored jointly by one model is more accurate
than comparing two independently-embedded vectors — too slow to run over a whole corpus, which
is exactly why it only reranks the top-N hybrid candidates rather than replacing dense search.
"""

from __future__ import annotations

import threading

from app.core.inference_lock import run_exclusive
from app.llm.models_config import get_model_config
from app.retrieval.hybrid import FusedHit


class CrossEncoderReranker:
    def __init__(self, model_name: str):
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self._model = CrossEncoder(self.model_name)

    def rerank(self, query: str, hits: list[FusedHit]) -> list[FusedHit]:
        if not hits:
            return []
        pairs = [(query, h.text) for h in hits]
        scores = run_exclusive(self._model.predict, pairs)
        rescored = [
            hit.model_copy(update={"rerank_score": float(score)})
            for hit, score in zip(hits, scores, strict=True)
        ]
        rescored.sort(key=lambda h: h.rerank_score or 0.0, reverse=True)
        return rescored


_loaded: dict[str, CrossEncoderReranker] = {}
_load_lock = threading.Lock()


def get_reranker(model_name: str | None = None) -> CrossEncoderReranker:
    """The reranker for `model_name`, or for the currently selected one. Loaded once each."""
    name = model_name or get_model_config().reranker
    if name not in _loaded:
        with _load_lock:
            if name not in _loaded:
                _loaded[name] = CrossEncoderReranker(name)
    return _loaded[name]


def loaded_reranker_names() -> list[str]:
    return list(_loaded)
