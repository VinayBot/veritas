from __future__ import annotations

from app.retrieval.hybrid import FusedHit
from app.retrieval.reranker import get_reranker


def test_reranker_scores_the_truly_relevant_passage_higher() -> None:
    reranker = get_reranker()
    hits = [
        FusedHit(
            chunk_id="irrelevant",
            score=0.5,
            text="The weather in Paris is usually mild in the spring.",
        ),
        FusedHit(
            chunk_id="relevant",
            score=0.4,  # deliberately lower initial score than the irrelevant one
            text="Employees accrue two days of paid vacation for every month worked.",
        ),
    ]
    reranked = reranker.rerank("How much vacation do employees get?", hits)
    assert reranked[0].chunk_id == "relevant"
    assert reranked[0].rerank_score is not None
    assert reranked[0].rerank_score > reranked[1].rerank_score


def test_reranker_handles_empty_hits() -> None:
    assert get_reranker().rerank("query", []) == []
