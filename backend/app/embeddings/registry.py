"""Embedding model registry: swappable sentence-transformers models, lazily loaded and cached
so picking a different model doesn't cost anything until it's actually used.

Candidates per the brief: BAAI/bge-small-en-v1.5, all-MiniLM-L6-v2 (baseline),
BAAI/bge-base-en-v1.5, intfloat/multilingual-e5-small, nomic-ai/nomic-embed-text-v1.5 — all
are valid `model_name` values here. Only the baseline is pulled by default here; see
docs/DECISIONS.md.
"""

from __future__ import annotations

import threading

import numpy as np

from app.core.inference_lock import run_exclusive

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
            dimension = len(
                run_exclusive(self._model.encode, ["probe"], show_progress_bar=False)[0]
            )
        self.dimension: int = dimension

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        return np.asarray(
            run_exclusive(
                self._model.encode, texts, normalize_embeddings=True, show_progress_bar=False
            )
        )

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


_loaded: dict[str, Embedder] = {}
_load_lock = threading.Lock()


def get_embedder(model_name: str | None = None) -> Embedder:
    """The embedder for `model_name`, or for the currently selected embedding model. Loaded
    once per model and kept; switching models does not evict the previous one, so a re-index
    can read with one and write with another."""
    from app.llm.models_config import get_model_config

    name = model_name or get_model_config().embedding
    if name not in _loaded:
        with _load_lock:
            if name not in _loaded:
                _loaded[name] = Embedder(name)
    return _loaded[name]


def loaded_embedder_names() -> list[str]:
    return list(_loaded)
