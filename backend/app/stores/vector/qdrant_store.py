"""Qdrant adapter — the second dense vector store, selected with VECTOR_STORE=qdrant.

Runs Qdrant in local (embedded) mode: the client stores its collections on disk under
DATA_DIR/qdrant, so no server or account is needed, the same way ChromaDB runs here. Point
QDRANT_URL at a server (e.g. the `qdrant` service in docker-compose) to use one instead.

It implements the same interface as ChromaVectorStore, including Chroma's filter shape
({"doc_id": x} or {"$and": [...]}) so callers never know which store they are talking to,
and returns the same score: cosine similarity mapped to [0, 1].
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

import numpy as np

from app.core.config import get_settings
from app.stores.vector.base import VectorHit
from app.stores.vector.chroma_store import COLLECTION_NAME, collection_for

# Qdrant point ids must be unsigned ints or UUIDs; chunk ids are arbitrary strings (variant
# chunks, the preflight probe), so each maps to a stable UUID and the original id travels in
# the payload.
_ID_NAMESPACE = uuid.UUID("6f1c3b52-4c1e-4b8e-9a52-6b0d0f1e7c11")
_CHUNK_ID = "chunk_id"
_TEXT = "text"


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(_ID_NAMESPACE, chunk_id))


def to_qdrant_filter(where: dict[str, Any] | None) -> Any:
    """Chroma's filter shape as a Qdrant Filter. Only equality and $and are used anywhere in
    the app; anything else is refused loudly rather than silently ignored."""
    if not where:
        return None
    from qdrant_client import models

    def conditions(clause: dict[str, Any]) -> list[Any]:
        if "$and" in clause:
            return [c for sub in clause["$and"] for c in conditions(sub)]
        out = []
        for key, value in clause.items():
            if key.startswith("$") or isinstance(value, dict):
                raise ValueError(f"Unsupported vector filter: {clause!r}")
            out.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
        return out

    return models.Filter(must=conditions(where))


class QdrantVectorStore:
    def __init__(self, client: Any, collection_name: str = COLLECTION_NAME) -> None:
        self.collection_name = collection_name
        self._client = client
        self._dim: int | None = None
        if client.collection_exists(collection_name):
            info = client.get_collection(collection_name)
            self._dim = int(info.config.params.vectors.size)

    def _ensure_collection(self, dim: int) -> None:
        if self._dim is not None:
            return
        from qdrant_client import models

        self._client.create_collection(
            self.collection_name,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )
        self._dim = dim

    def count(self) -> int:
        if self._dim is None:
            return 0
        return int(self._client.count(self.collection_name, exact=True).count)

    def add(
        self,
        ids: list[str],
        embeddings: np.ndarray,
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        if not ids:
            return
        from qdrant_client import models

        self._ensure_collection(int(embeddings.shape[1]))
        points = [
            models.PointStruct(
                id=point_id(chunk_id),
                vector=vector.tolist(),
                payload={**meta, _CHUNK_ID: chunk_id, _TEXT: doc},
            )
            for chunk_id, vector, doc, meta in zip(
                ids, embeddings, documents, metadatas, strict=True
            )
        ]
        self._client.upsert(self.collection_name, points=points)

    def query(
        self, embedding: np.ndarray, k: int, where: dict[str, Any] | None = None
    ) -> list[VectorHit]:
        if self._dim is None or k <= 0:
            return []
        response = self._client.query_points(
            self.collection_name,
            query=embedding.tolist(),
            limit=k,
            query_filter=to_qdrant_filter(where),
            with_payload=True,
        )
        hits: list[VectorHit] = []
        for point in response.points:
            payload = dict(point.payload or {})
            chunk_id = str(payload.pop(_CHUNK_ID, point.id))
            text = str(payload.pop(_TEXT, ""))
            # Cosine similarity s in [-1, 1] -> (1 + s) / 2, the same [0, 1] score Chroma's
            # adapter derives from cosine distance (1 - d / 2 with d = 1 - s).
            score = (1.0 + float(point.score)) / 2.0
            hits.append(VectorHit(chunk_id=chunk_id, score=score, text=text, metadata=payload))
        return hits

    def delete_where(self, where: dict[str, Any]) -> None:
        if self._dim is None:
            return
        from qdrant_client import models

        self._client.delete(
            self.collection_name,
            points_selector=models.FilterSelector(filter=to_qdrant_filter(where)),
        )

    def delete_by_doc(self, doc_id: str) -> None:
        self.delete_where({"doc_id": doc_id})

    def get_embeddings(self, ids: list[str]) -> dict[str, np.ndarray]:
        if not ids or self._dim is None:
            return {}
        points = self._client.retrieve(
            self.collection_name,
            ids=[point_id(i) for i in ids],
            with_vectors=True,
            with_payload=[_CHUNK_ID],
        )
        return {
            str((p.payload or {}).get(_CHUNK_ID)): np.asarray(p.vector)
            for p in points
            if p.vector is not None
        }


_client: Any = None
_stores: dict[str, QdrantVectorStore] = {}
_lock = threading.Lock()


def _get_client() -> Any:
    global _client
    with _lock:
        if _client is None:
            from qdrant_client import QdrantClient

            settings = get_settings()
            if settings.qdrant_url:
                _client = QdrantClient(url=settings.qdrant_url)
            else:
                path = settings.data_dir / "qdrant"
                path.mkdir(parents=True, exist_ok=True)
                _client = QdrantClient(path=str(path))
    return _client


def get_qdrant_store(
    embedding_model: str | None = None, variants: bool = False
) -> QdrantVectorStore:
    if embedding_model is None:
        from app.llm.models_config import get_model_config

        embedding_model = get_model_config().embedding
    name = collection_for(embedding_model, variants)
    if name not in _stores:
        client = _get_client()
        with _lock:
            if name not in _stores:
                _stores[name] = QdrantVectorStore(client, name)
    return _stores[name]


def delete_document_everywhere_qdrant(doc_id: str) -> None:
    client = _get_client()
    for collection in client.get_collections().collections:
        if collection.name.startswith(COLLECTION_NAME):
            store = _stores.get(collection.name) or QdrantVectorStore(client, collection.name)
            store.delete_by_doc(doc_id)
