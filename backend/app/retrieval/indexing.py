"""Chunk -> persist -> embed -> index(Chroma + BM25). The one path by which chunks enter both
the dense and sparse stores, so they can never drift out of sync with the chunks table.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from app.chunking.base import Chunk, Chunker
from app.chunking.models import ChunkRow
from app.chunking.registry import get_baseline_chunker
from app.core.db import session_scope
from app.core.tracing import trace_bus
from app.embeddings.registry import get_embedder
from app.stores.bm25 import rebuild_bm25_index
from app.stores.vector.chroma_store import get_vector_store


async def index_document(doc_id: str, text: str, chunker: Chunker | None = None) -> list[Chunk]:
    async with trace_bus.stage(doc_id, "chunk", from_stage="pii_vault", to_stage="embed") as h:
        chunker = chunker or get_baseline_chunker()
        chunks = await asyncio.to_thread(chunker.chunk, doc_id, text)
        h.set_metric("chunk_count", len(chunks))
        h.set_metric("strategy", chunker.name)
        if not chunks:
            h.set_output("no chunks produced")
            return []
        h.set_output(f"{len(chunks)} chunks")

        now = datetime.now(UTC)
        async with session_scope() as session:
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
                        extra=c.extra,
                        created_at=now,
                    )
                )
            await session.commit()

    async with trace_bus.stage(doc_id, "embed", from_stage="chunk", to_stage="index") as h:
        embedder = get_embedder()
        embeddings = await asyncio.to_thread(embedder.embed, [c.text for c in chunks])
        h.set_metric("model", embedder.model_name)
        h.set_metric("dimension", embedder.dimension)
        h.set_output(f"{len(chunks)} vectors x {embedder.dimension}d")

    async with trace_bus.stage(doc_id, "index", from_stage="embed", to_stage="profile") as h:
        get_vector_store().add(
            ids=[c.chunk_id for c in chunks],
            embeddings=embeddings,
            documents=[c.text for c in chunks],
            metadatas=[
                {
                    "doc_id": c.doc_id,
                    "parent_id": c.parent_id or "",
                    "strategy": c.strategy,
                    "section_path": c.section_path or "",
                }
                for c in chunks
            ],
        )
        await rebuild_bm25_index()
        h.set_output("chroma + bm25 updated")

    return chunks
