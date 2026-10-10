from __future__ import annotations

from conftest import wait_for_document
from httpx import AsyncClient

from app.evaluation.datasets import generate_dataset
from app.profiler.advisor import build_recommendation, recommend_mode
from app.profiler.features import profile_document
from app.profiler.tournament import default_candidates, run_tournament


async def test_full_tournament_and_advisor_on_a_real_document(client: AsyncClient) -> None:
    content = (
        b"# Vacation Policy\n\n"
        b"Employees accrue two paid vacation days per month of service, up to a maximum of "
        b"twenty-four days per year. Managers must approve requests at least two weeks in "
        b"advance. Unused days roll over, capped at ten days.\n\n"
        b"# Expense Policy\n\n"
        b"Submit expense reports within thirty days of purchase for reimbursement. Reports "
        b"over five hundred dollars require manager approval before submission.\n\n"
        b"# Remote Work\n\n"
        b"Employees may work remotely up to three days per week with manager approval. "
        b"Equipment requests go through the IT helpdesk portal.\n"
    )
    files = {"file": ("handbook.md", content, "text/markdown")}
    upload = await client.post("/api/v1/documents/upload", files=files)
    document_id = upload.json()["document_id"]
    await wait_for_document(client, document_id)

    doc_resp = await client.get(f"/api/v1/documents/{document_id}")
    masked_text = None
    # masked_text isn't exposed via the API by design (Phase 2) — pull it directly for this test.
    from app.core.db import session_scope
    from app.ingestion.models import Document

    async with session_scope() as session:
        doc = await session.get(Document, document_id)
        masked_text = doc.masked_text

    profile = await profile_document(document_id, masked_text, doc_resp.json()["language"], None)
    assert profile.tokens > 0

    eval_items = await generate_dataset(document_id, target_size=10)
    assert eval_items, "expected at least one real generated eval item"
    assert {item.category for item in eval_items} <= {
        "factoid",
        "multi_hop",
        "comparison",
        "unanswerable",
        "pii",
    }

    from sqlalchemy import select

    from app.chunking.models import ChunkRow

    async with session_scope() as session:
        rows = (
            (await session.execute(select(ChunkRow).where(ChunkRow.doc_id == document_id)))
            .scalars()
            .all()
        )
    ground_truth_by_id = {r.chunk_id: r.text for r in rows}

    tournament = await run_tournament(
        masked_text, eval_items, ground_truth_by_id, candidates=default_candidates()[:3]
    )
    assert tournament.baseline is not None
    assert tournament.winner is not None
    for result in tournament.results:
        assert result.retrieval_metrics["n"] >= 0

    recommendation = build_recommendation(profile, tournament)
    assert recommendation is not None
    assert recommendation.rationale
    assert recommendation.suggested_mode in ("hybrid", "graph", "agentic")


def test_recommend_mode_graph_for_relation_dense_profile() -> None:
    from app.profiler.features import DocumentProfile

    profile = DocumentProfile(
        document_id="d1",
        pages_estimated=5,
        tokens=2000,
        language="en",
        heading_density=0.05,
        table_ratio=0.0,
        list_ratio=0.0,
        code_ratio=0.0,
        avg_sentence_length=12,
        avg_paragraph_length=40,
        duplication_ratio=0.0,
        ocr_confidence=None,
        entity_density=10.0,
        relation_density=5.0,  # above threshold
        document_type="mixed",
    )
    mode, reason = recommend_mode(profile)
    assert mode == "graph"
    assert "relation density" in reason.lower()


def test_recommend_mode_hybrid_for_short_simple_profile() -> None:
    from app.profiler.features import DocumentProfile

    profile = DocumentProfile(
        document_id="d2",
        pages_estimated=1,
        tokens=500,
        language="en",
        heading_density=0.0,
        table_ratio=0.0,
        list_ratio=0.0,
        code_ratio=0.0,
        avg_sentence_length=10,
        avg_paragraph_length=30,
        duplication_ratio=0.0,
        ocr_confidence=None,
        entity_density=1.0,
        relation_density=0.0,
        document_type="faq",
    )
    mode, _ = recommend_mode(profile)
    assert mode == "hybrid"
