"""ChromaDB adapter — the default dense vector store. Behind the VectorStore interface so
Qdrant can be swapped in later via config (see docs/DECISIONS.md on why Qdrant isn't built yet).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, cast

import numpy as np

from app.core.config import get_settings
from app.stores.vector.base import VectorHit

COLLECTION_NAME = "chunks"


class ChromaVectorStore:
    def __init__(self) -> None:
        import chromadb

        settings = get_settings()
        persist_dir = settings.data_dir / "chroma"
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(
            COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )

    def add(
        self,
        ids: list[str],
        embeddings: np.ndarray,
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        if not ids:
            return
        self._collection.upsert(
            ids=ids,
            embeddings=embeddings.tolist(),
            documents=documents,
            # Our metadata values are always str — Chroma's stub just wants an explicit cast.
            metadatas=cast(Any, metadatas),
        )

    def query(
        self, embedding: np.ndarray, k: int, where: dict[str, Any] | None = None
    ) -> list[VectorHit]:
        if self._collection.count() == 0:
            return []
        result = self._collection.query(
            query_embeddings=[embedding.tolist()],
            n_results=min(k, self._collection.count()),
            where=where,
        )
        hits: list[VectorHit] = []
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        for chunk_id, doc, meta, distance in zip(ids, documents, metadatas, distances, strict=True):
            # Chroma returns cosine *distance*; convert to a similarity score in [0, 1].
            score = 1.0 - (distance / 2.0)
            hits.append(
                VectorHit(chunk_id=chunk_id, score=score, text=doc, metadata=dict(meta or {}))
            )
        return hits

    def delete_by_doc(self, doc_id: str) -> None:
        self._collection.delete(where={"doc_id": doc_id})

    def get_embeddings(self, ids: list[str]) -> dict[str, np.ndarray]:
        """Reuses the exact vectors stored at index time, rather than re-embedding candidate
        text at query time (cheaper, and guaranteed consistent with what was indexed)."""
        if not ids:
            return {}
        result = self._collection.get(ids=ids, include=["embeddings"])
        got_ids = result.get("ids") or []
        got_embeddings = result.get("embeddings")
        if got_embeddings is None:
            return {}
        return {
            chunk_id: np.asarray(vec) for chunk_id, vec in zip(got_ids, got_embeddings, strict=True)
        }


@lru_cache(maxsize=1)
def get_vector_store() -> ChromaVectorStore:
    return ChromaVectorStore()
