"""Index variants: an alternative chunking of a document, built on demand.

A document's working index is one chunking (recursive 512/64 unless the chunking advisor's
suggestion was accepted). Two strategies need a different one. Building every variant at
ingest would roughly triple ingest time for something most documents never use, so a
variant is built the first time a strategy that needs it is chosen, with real progress, and
kept. The working index is never modified by this.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import delete, func, select

from app.chunking.models import ChunkRow
from app.chunking.registry import get_chunker
from app.core.db import session_scope
from app.embeddings.registry import get_embedder
from app.ingestion.models import Document
from app.rag_engines.registry import INDEX_VARIANTS
from app.stores.bm25 import rebuild_bm25_index
from app.stores.vector import get_vector_store

Progress = Callable[[float, str], Awaitable[None]]


class VariantError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


async def variant_chunk_count(document_id: str, variant: str) -> int:
    async with session_scope() as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ChunkRow)
                    .where(ChunkRow.doc_id == document_id, ChunkRow.variant == variant)
                )
            ).scalar_one()
        )


async def has_variant(document_id: str, variant: str) -> bool:
    if variant == "default":
        return True
    return await variant_chunk_count(document_id, variant) > 0


async def _noop(_fraction: float, _message: str) -> None:
    return None


async def build_variant(document_id: str, variant_id: str, progress: Progress = _noop) -> int:
    """Chunks, embeds and indexes `document_id` under `variant_id`. Returns the chunk count.
    Rebuilding replaces the previous build of the same variant."""
    spec = INDEX_VARIANTS.get(variant_id)
    if spec is None:
        raise VariantError("unknown_variant", f"Unknown index variant: {variant_id!r}")
    async with session_scope() as session:
        doc = await session.get(Document, document_id)
    if doc is None:
        raise VariantError("document_not_found", f"No document with id {document_id}")
    if doc.masked_text is None:
        raise VariantError("document_not_ready", "The document has not finished ingesting.")

    await progress(0.05, f"Chunking with {spec.description.lower()}")
    chunker = get_chunker(spec.chunker, **spec.kwargs)
    # The variant gets its own chunk ids, so it can never collide with the working index.
    chunks = await asyncio.to_thread(chunker.chunk, document_id, doc.masked_text)
    if not chunks:
        raise VariantError("variant_empty", "That chunking produced no chunks for this document.")

    await progress(0.3, f"Embedding {len(chunks)} chunks")
    embedder = get_embedder()
    embeddings = await asyncio.to_thread(embedder.embed, [c.text for c in chunks])

    await progress(0.75, "Writing the dense and keyword indexes")
    store = get_vector_store(variants=True)
    store.delete_where({"$and": [{"doc_id": document_id}, {"variant": variant_id}]})
    now = datetime.now(UTC)
    async with session_scope() as session:
        await session.execute(
            delete(ChunkRow).where(ChunkRow.doc_id == document_id, ChunkRow.variant == variant_id)
        )
        for c in chunks:
            session.add(
                ChunkRow(
                    chunk_id=c.chunk_id,
                    doc_id=c.doc_id,
                    parent_id=c.parent_id,
                    text=c.text,
                    page=c.page,
                    section_path=c.section_path,
                    token_count=c.token_count,
                    pii_token_count=c.pii_token_count,
                    strategy=c.strategy,
                    variant=variant_id,
                    extra=c.extra,
                    created_at=now,
                )
            )
        await session.commit()
    store.add(
        ids=[c.chunk_id for c in chunks],
        embeddings=embeddings,
        documents=[c.text for c in chunks],
        metadatas=[
            {"doc_id": c.doc_id, "variant": variant_id, "strategy": c.strategy} for c in chunks
        ],
    )
    await rebuild_bm25_index()
    await progress(1.0, f"Built {len(chunks)} chunks")
    return len(chunks)
