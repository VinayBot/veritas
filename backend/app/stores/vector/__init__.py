"""The dense vector store, chosen by VECTOR_STORE: "chroma" (default) or "qdrant". Both run
locally on disk with no server and implement the same interface, so the rest of the app only
ever imports from here."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings


def get_vector_store(embedding_model: str | None = None, variants: bool = False) -> Any:
    if get_settings().vector_store == "qdrant":
        from app.stores.vector.qdrant_store import get_qdrant_store

        return get_qdrant_store(embedding_model, variants)
    from app.stores.vector.chroma_store import get_vector_store as get_chroma_store

    return get_chroma_store(embedding_model, variants)


def delete_document_everywhere(doc_id: str) -> None:
    if get_settings().vector_store == "qdrant":
        from app.stores.vector.qdrant_store import delete_document_everywhere_qdrant

        delete_document_everywhere_qdrant(doc_id)
        return
    from app.stores.vector.chroma_store import delete_document_everywhere as delete_chroma

    delete_chroma(doc_id)
