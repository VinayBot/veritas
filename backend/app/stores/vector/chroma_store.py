"""ChromaDB adapter — the default dense vector store. Behind the VectorStore interface so
Qdrant can be swapped in later via config (see docs/DECISIONS.md on why Qdrant isn't built yet).
"""

from __future__ import annotations

import threading
from typing import Any, cast

import numpy as np

from app.core.config import get_settings
from app.stores.vector.base import VectorHit

COLLECTION_NAME = "chunks"
BASELINE_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def collection_for(embedding_model: str, variants: bool = False) -> str:
    """Collection name for an embedding model. Vectors from different models have different
    dimensions and meanings, so they never share a collection; index variants (alternative
    chunkings) get their own too, so the working index is never touched by building one.
    The baseline model keeps the original name, so existing data needs no migration."""
    import re

    base = COLLECTION_NAME
    if embedding_model != BASELINE_EMBEDDING_MODEL:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", embedding_model).strip("-").lower()[:40]
        base = f"{COLLECTION_NAME}--{slug}"
    return f"{base}--variants" if variants else base


class ChromaVectorStore:
    def __init__(self, client: Any, collection_name: str = COLLECTION_NAME) -> None:
        self.collection_name = collection_name
        self._collection = client.get_or_create_collection(
            collection_name, metadata={"hnsw:space": "cosine"}
        )

    def count(self) -> int:
        return int(self._collection.count())

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

    def delete_where(self, where: dict[str, Any]) -> None:
        self._collection.delete(where=where)

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


_client: Any = None
_stores: dict[str, ChromaVectorStore] = {}
_lock = threading.Lock()


def get_vector_store(
    embedding_model: str | None = None, variants: bool = False
) -> ChromaVectorStore:
    """The store for the active embedding model (or the one named). One client per process,
    guarded by a lock because the first call can come from two worker threads at once
    (startup warm-up and a health probe), and constructing two PersistentClients for the same
    path concurrently fails inside chromadb."""
    global _client
    if embedding_model is None:
        from app.llm.models_config import get_model_config

        embedding_model = get_model_config().embedding
    name = collection_for(embedding_model, variants)
    if name not in _stores:
        with _lock:
            if _client is None:
                import chromadb

                persist_dir = get_settings().data_dir / "chroma"
                persist_dir.mkdir(parents=True, exist_ok=True)
                _client = chromadb.PersistentClient(path=str(persist_dir))
            if name not in _stores:
                _stores[name] = ChromaVectorStore(_client, name)
    return _stores[name]


def delete_document_everywhere(doc_id: str) -> None:
    """Removes a document's vectors from every collection that exists (every embedding model
    it was ever indexed with, working index and variants alike)."""
    get_vector_store()  # make sure the client exists
    for collection in _client.list_collections():
        name = getattr(collection, "name", collection)
        if str(name).startswith(COLLECTION_NAME):
            _client.get_collection(str(name)).delete(where={"doc_id": doc_id})
