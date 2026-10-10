"""The Retriever node's tools: hybrid_search, graph_traverse, pii_vault_lookup. (metadata_filter
is just the existing doc_id scoping already built into hybrid_search — not a separate tool with
its own logic; web_fetch is only relevant in URL-ingestion mode and isn't wired into the agent
yet, since no scenario in this build exercises an agent fetching a fresh URL mid-conversation.)
"""

from __future__ import annotations

from sqlalchemy import select

from app.chunking.models import ChunkRow
from app.core.db import session_scope
from app.graphrag.service import graph_query
from app.privacy import vault
from app.privacy.detector import detect
from app.privacy.tokenizer import make_token
from app.retrieval import service as retrieval_service


async def hybrid_search_tool(query_text: str, doc_id: str | None, k: int = 5) -> list[dict]:
    hits = await retrieval_service.search(
        query_text, k=k, doc_id=doc_id, mode="hybrid", rerank=True
    )
    return [
        {
            "chunk_id": h.chunk_id,
            "text": h.text,
            "score": h.rerank_score if h.rerank_score is not None else h.score,
            "source": "hybrid",
        }
        for h in hits
    ]


async def graph_traverse_tool(query_text: str, hops: int = 2) -> list[dict]:
    result = graph_query(query_text, hops=hops)
    chunk_ids = {e["chunk_id"] for e in result["edges"] if e.get("chunk_id")}

    chunks_by_id: dict[str, str] = {}
    if chunk_ids:
        async with session_scope() as session:
            rows = await session.execute(
                select(ChunkRow.chunk_id, ChunkRow.text).where(ChunkRow.chunk_id.in_(chunk_ids))
            )
            chunks_by_id = dict(rows.all())

    hits: list[dict] = []
    seen: set[str] = set()
    for edge in result["edges"]:
        cid = edge.get("chunk_id")
        if cid and cid in chunks_by_id and cid not in seen:
            seen.add(cid)
            hits.append(
                {"chunk_id": cid, "text": chunks_by_id[cid], "score": 0.5, "source": "graph"}
            )

    if not hits and result["linked_entities"]:
        names = {n["id"]: n["name"] for n in result["linked_entities"]}
        names.update({n: n for n in result["nodes"] if n not in names})
        path_desc = "; ".join(
            f"{names.get(e['source'], e['source'])} {e['predicate']} "
            f"{names.get(e['target'], e['target'])}"
            for e in result["edges"][:10]
        )
        if path_desc:
            hits.append(
                {
                    "chunk_id": "graph-path",
                    "text": f"Graph relationships found: {path_desc}",
                    "score": 0.4,
                    "source": "graph",
                }
            )

    return hits


async def pii_vault_lookup_tool(query_text: str, session_id: str, reveal_pii: bool) -> list[dict]:
    if not reveal_pii:
        return [
            {
                "chunk_id": "pii-lookup-denied",
                "text": (
                    "This looks like a request for personal contact information. Enable "
                    "'Reveal PII' for this session to allow looking up vault values."
                ),
                "score": 0.3,
                "source": "pii_vault",
            }
        ]

    detected = detect(query_text)
    if not detected:
        return []

    hits = []
    for ent in detected:
        token = make_token(ent.entity_type, ent.text)
        value = await vault.reveal(token, session_id=session_id)
        if value is not None:
            hits.append(
                {
                    "chunk_id": f"pii-{token}",
                    "text": f"{ent.entity_type}: {value}",
                    "score": 0.9,
                    "source": "pii_vault",
                }
            )
    return hits
