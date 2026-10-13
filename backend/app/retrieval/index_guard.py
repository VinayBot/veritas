"""Refuses to search an index built with a different embedding model.

Vectors from two embedding models are not comparable: searching one model's index with
another's query vector returns confident-looking nonsense (or fails outright on a dimension
mismatch). After the embedding model is changed, a document stays unsearchable until it is
re-indexed — it is never silently served from a mismatched index.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select

from app.chunking.models import ChunkRow
from app.core.config import get_settings
from app.core.db import session_scope
from app.embeddings.registry import get_embedder
from app.ingestion.models import Document
from app.llm.models_config import get_model_config
from app.stores.vector.chroma_store import get_vector_store


class IndexMismatchError(Exception):
    def __init__(self, document_id: str, built_with: str, active: str) -> None:
        self.document_id = document_id
        self.built_with = built_with
        self.active = active
        super().__init__(
            f"This document's index was built with {built_with}, but the embedding model is "
            f"now {active}. Re-index it (Settings → Models) before asking questions."
        )


def built_with(document: Document) -> str:
    """Documents indexed before this was recorded were all built with the configured
    baseline."""
    return document.embedding_model or get_settings().embedding_model


async def assert_index_current(document_id: str | None) -> None:
    if document_id is None:
        return
    async with session_scope() as session:
        document = await session.get(Document, document_id)
    if document is None or document.status != "ready":
        return
    active = get_model_config().embedding
    if built_with(document) != active:
        raise IndexMismatchError(document_id, built_with(document), active)


async def index_status() -> dict:
    active = get_model_config().embedding
    async with session_scope() as session:
        rows = (
            (await session.execute(select(Document).where(Document.status == "ready")))
            .scalars()
            .all()
        )
    documents = [
        {
            "id": d.id,
            "filename": d.filename,
            "embedding_model": built_with(d),
            "chunk_count": d.chunk_count,
            "stale": built_with(d) != active,
        }
        for d in rows
    ]
    stale = [d for d in documents if d["stale"]]
    return {
        "active_embedding_model": active,
        "ready_documents": len(documents),
        "stale_count": len(stale),
        "stale_chunks": sum(d["chunk_count"] or 0 for d in stale),
        "stale_documents": stale[:200],
    }


async def reindex_document(document_id: str) -> int:
    """Re-embeds a document's existing chunks (working index and any variants) with the
    active embedding model. Chunk text and ids are unchanged, so the keyword index, the graph
    and evaluation ground truth stay valid. Returns the number of chunks embedded."""
    async with session_scope() as session:
        rows = (
            (await session.execute(select(ChunkRow).where(ChunkRow.doc_id == document_id)))
            .scalars()
            .all()
        )
    embedder = get_embedder()
    embedded = 0
    for is_variant in (False, True):
        subset = [r for r in rows if (r.variant != "default") == is_variant]
        store = get_vector_store(variants=is_variant)
        store.delete_by_doc(document_id)
        if not subset:
            continue
        vectors = await asyncio.to_thread(embedder.embed, [r.text for r in subset])
        store.add(
            ids=[r.chunk_id for r in subset],
            embeddings=vectors,
            documents=[r.text for r in subset],
            metadatas=[
                {
                    "doc_id": r.doc_id,
                    "variant": r.variant,
                    "strategy": r.strategy,
                    "section_path": r.section_path or "",
                    "parent_id": r.parent_id or "",
                }
                for r in subset
            ],
        )
        embedded += len(subset)
    async with session_scope() as session:
        document = await session.get(Document, document_id)
        if document is not None:
            document.embedding_model = embedder.model_name
            document.updated_at = datetime.now(UTC)
            await session.commit()
    return embedded


async def reindex_stale(
    document_ids: list[str] | None, progress: Callable[[float, str], Awaitable[None]]
) -> dict:
    status = await index_status()
    targets = [
        d for d in status["stale_documents"] if document_ids is None or d["id"] in document_ids
    ]
    total = len(targets)
    chunks = 0
    for index, doc in enumerate(targets):
        await progress(
            index / max(total, 1), f"Re-embedding {doc['filename']} ({index + 1}/{total})"
        )
        chunks += await reindex_document(doc["id"])
    await progress(1.0, f"Re-indexed {total} document(s), {chunks} chunks")
    return {
        "documents": total,
        "chunks": chunks,
        "embedding_model": status["active_embedding_model"],
    }
