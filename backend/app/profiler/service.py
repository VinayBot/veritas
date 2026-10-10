"""Orchestrates the profiler + advisor + accept/ignore flow: wraps the pure profiler/advisor/
tournament modules (which only take plain text/dataclasses) with the real document lookup,
dataset generation, persistence, and — on "accept" — a real re-chunk/re-embed/re-index of the
document using the suggested chunking config.

The tournament only runs when the document's current chunking produced enough chunks to make a
chunking-strategy comparison meaningful (MIN_CHUNKS_FOR_TOURNAMENT): on a one- or two-chunk
document every candidate strategy produces almost the same single chunk, so comparing them
would be measuring noise, not a real signal. Below that threshold the document is still
profiled (cheap, real) but gets no advisor recommendation — recorded as a scope decision in
docs/DECISIONS.md, not silently faked as "no gain found."
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from app.chunking.models import ChunkRow
from app.chunking.registry import get_chunker
from app.core.db import session_scope
from app.evaluation.datasets import generate_dataset
from app.evaluation.models import AdvisorRecommendation as AdvisorRecommendationRow
from app.graphrag.service import build_graph_for_document
from app.ingestion.models import Document
from app.profiler.advisor import AdvisorRecommendation, build_recommendation
from app.profiler.features import DocumentProfile, profile_document
from app.profiler.tournament import CandidateResult, TournamentResult, run_tournament
from app.retrieval.indexing import index_document
from app.stores.graph.networkx_store import get_graph_store
from app.stores.vector.chroma_store import get_vector_store

MIN_CHUNKS_FOR_TOURNAMENT = 3
AUTO_EVAL_TARGET_SIZE = 8
VALID_DECISIONS = ("accept", "ignore")


class AdvisorError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


async def get_document_or_raise(document_id: str) -> Document:
    async with session_scope() as session:
        doc = await session.get(Document, document_id)
    if doc is None:
        raise AdvisorError("document_not_found", f"No document with id {document_id}")
    return doc


async def _chunk_count(document_id: str) -> int:
    async with session_scope() as session:
        rows = (
            await session.execute(select(ChunkRow.chunk_id).where(ChunkRow.doc_id == document_id))
        ).all()
    return len(rows)


async def _ground_truth_map(document_id: str) -> dict[str, str]:
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(ChunkRow.chunk_id, ChunkRow.text).where(ChunkRow.doc_id == document_id)
            )
        ).all()
    return {chunk_id: text for chunk_id, text in rows}


def _candidate_config_dict(result: CandidateResult) -> dict[str, Any]:
    return {
        "name": result.config.name,
        "chunking_strategy": result.config.chunking_strategy,
        "chunking_kwargs": result.config.chunking_kwargs,
        "rerank": result.config.rerank,
        "llm_model": result.config.llm_model,
    }


def _candidate_metrics_dict(result: CandidateResult) -> dict[str, Any]:
    return {
        "retrieval_metrics": result.retrieval_metrics,
        "faithfulness": result.faithfulness,
        "avg_latency_ms": result.avg_latency_ms,
        "index_size": result.index_size,
        "composite_score": result.composite_score,
    }


def candidate_result_out(result: CandidateResult) -> dict[str, Any]:
    return {**_candidate_config_dict(result), **_candidate_metrics_dict(result)}


async def profile(
    document_id: str, text: str, language: str | None, ocr_confidence: float | None
) -> DocumentProfile:
    return await profile_document(document_id, text, language, ocr_confidence)


async def run_advisor(
    document_id: str,
    document_text: str,
    doc_profile: DocumentProfile,
    dataset_target_size: int = AUTO_EVAL_TARGET_SIZE,
) -> AdvisorRecommendation | None:
    """Real tournament against a freshly-generated synthetic dataset. Returns None — not a
    placeholder recommendation — when there isn't enough indexed content to compare chunking
    strategies meaningfully, or the LLM is unavailable so no dataset could be generated."""
    if await _chunk_count(document_id) < MIN_CHUNKS_FOR_TOURNAMENT:
        return None

    eval_items = await generate_dataset(document_id, target_size=dataset_target_size)
    if not eval_items:
        return None

    ground_truth = await _ground_truth_map(document_id)
    tournament = await run_tournament(document_text, eval_items, ground_truth)
    recommendation = build_recommendation(doc_profile, tournament)
    if recommendation is None:
        return None

    await _save_recommendation(document_id, recommendation, tournament)
    return recommendation


async def _save_recommendation(
    document_id: str, recommendation: AdvisorRecommendation, tournament: TournamentResult
) -> AdvisorRecommendationRow:
    row = AdvisorRecommendationRow(
        id=str(uuid.uuid4()),
        document_id=document_id,
        baseline_config=_candidate_config_dict(recommendation.baseline),
        suggested_config=_candidate_config_dict(recommendation.suggested),
        baseline_metrics=_candidate_metrics_dict(recommendation.baseline),
        suggested_metrics=_candidate_metrics_dict(recommendation.suggested),
        gain_ndcg=recommendation.gain_ndcg_points,
        rationale=recommendation.rationale,
        suggested_mode=recommendation.suggested_mode,
        mode_reason=recommendation.mode_reason,
        candidates=[candidate_result_out(r) for r in tournament.results],
        decision=None,
        created_at=datetime.now(UTC),
        decided_at=None,
    )
    async with session_scope() as session:
        session.add(row)
        await session.commit()
    return row


async def get_latest_recommendation(document_id: str) -> AdvisorRecommendationRow | None:
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(AdvisorRecommendationRow)
                    .where(AdvisorRecommendationRow.document_id == document_id)
                    .order_by(AdvisorRecommendationRow.created_at.desc())
                    .limit(1)
                )
            )
            .scalars()
            .all()
        )
    return rows[0] if rows else None


async def _reindex_with_suggested_config(document_id: str, row: AdvisorRecommendationRow) -> None:
    """The real "accept" action: deletes the document's current chunks (SQL rows, vectors, and
    the graph edges that referenced their chunk_ids) and rebuilds all three from the suggested
    candidate's chunking config. Entity *nodes* are kept — they're resolved by canonical name,
    not by chunk, and may be shared with other documents."""
    doc = await get_document_or_raise(document_id)
    if doc.masked_text is None:
        raise AdvisorError("document_not_ready", f"Document {document_id} has no indexed text")

    chunker = get_chunker(
        row.suggested_config["chunking_strategy"], **row.suggested_config["chunking_kwargs"]
    )

    async with session_scope() as session:
        await session.execute(delete(ChunkRow).where(ChunkRow.doc_id == document_id))
        await session.commit()
    get_vector_store().delete_by_doc(document_id)
    get_graph_store().remove_doc_edges(document_id)

    chunks = await index_document(document_id, doc.masked_text, chunker=chunker)
    graph_stats = await build_graph_for_document(document_id, chunks)
    get_graph_store().save()

    async with session_scope() as session:
        fresh = await session.get(Document, document_id)
        if fresh is not None:
            fresh.chunk_count = len(chunks)
            fresh.chunk_strategy = chunks[0].strategy if chunks else None
            fresh.graph_entity_count = graph_stats["entities"]
            fresh.graph_triple_count = graph_stats["triples"]
            fresh.updated_at = datetime.now(UTC)
            await session.commit()


async def record_decision(document_id: str, decision: str) -> AdvisorRecommendationRow:
    if decision not in VALID_DECISIONS:
        raise AdvisorError("invalid_decision", f"decision must be one of {VALID_DECISIONS}")

    row = await get_latest_recommendation(document_id)
    if row is None:
        raise AdvisorError("no_recommendation", f"No advisor recommendation for {document_id}")

    if decision == "accept":
        await _reindex_with_suggested_config(document_id, row)

    async with session_scope() as session:
        fresh = await session.get(AdvisorRecommendationRow, row.id)
        assert fresh is not None
        fresh.decision = decision
        fresh.decided_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(fresh)
        return fresh
