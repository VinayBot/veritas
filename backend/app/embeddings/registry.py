"""Embedding model registry: swappable sentence-transformers models, lazily loaded and cached
so picking a different model doesn't cost anything until it's actually used.

Candidates per the brief: BAAI/bge-small-en-v1.5, all-MiniLM-L6-v2 (baseline),
BAAI/bge-base-en-v1.5, intfloat/multilingual-e5-small, nomic-ai/nomic-embed-text-v1.5 — all
are valid `model_name` values here. Only the baseline is pulled by default here; see
docs/DECISIONS.md.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from app.core.config import get_settings

CANDIDATE_MODELS = (
    "sentence-transformers/all-MiniLM-L6-v2",
    "BAAI/bge-small-en-v1.5",
    "BAAI/bge-base-en-v1.5",
    "intfloat/multilingual-e5-small",
    "nomic-ai/nomic-embed-text-v1.5",
)


class Embedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name, trust_remote_code=True)
        dimension = self._model.get_embedding_dimension()
        if dimension is None:
            # Some custom (trust_remote_code) models don't report this upfront — infer it.
            dimension = len(self._model.encode(["probe"], show_progress_bar=False)[0])
        self.dimension: int = dimension

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        return np.asarray(
            self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        )

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


@lru_cache(maxsize=3)
def get_embedder(model_name: str | None = None) -> Embedder:
    return Embedder(model_name or get_settings().embedding_model)
