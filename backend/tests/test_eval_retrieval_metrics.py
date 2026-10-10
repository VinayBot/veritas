from __future__ import annotations

import math

from app.evaluation.metrics.retrieval import (
    RetrievalMetricsAccumulator,
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_precision_at_k() -> None:
    assert precision_at_k(["a", "b", "c"], {"a", "c"}, k=3) == 2 / 3
    assert precision_at_k(["a", "b", "c"], {"z"}, k=3) == 0.0
    assert precision_at_k([], {"a"}, k=3) == 0.0


def test_recall_at_k() -> None:
    assert recall_at_k(["a", "b", "c"], {"a", "c", "d"}, k=3) == 2 / 3
    assert recall_at_k(["a"], set(), k=3) == 0.0


def test_hit_at_k() -> None:
    assert hit_at_k(["a", "b"], {"b"}, k=2) == 1.0
    assert hit_at_k(["a", "b"], {"z"}, k=2) == 0.0


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(["a", "b", "c"], {"c"}) == 1 / 3
    assert reciprocal_rank(["a", "b", "c"], {"a"}) == 1.0
    assert reciprocal_rank(["a", "b"], {"z"}) == 0.0


def test_ndcg_at_k_perfect_ranking_is_one() -> None:
    # The single relevant doc at rank 1 is the best possible arrangement -> nDCG == 1.0
    assert ndcg_at_k(["a", "b", "c"], {"a"}, k=3) == 1.0


def test_ndcg_at_k_worse_ranking_scores_lower() -> None:
    best = ndcg_at_k(["a", "b", "c"], {"a"}, k=3)
    worse = ndcg_at_k(["b", "c", "a"], {"a"}, k=3)
    assert worse < best
    # Hand-computed: DCG = 1/log2(3+1) = 1/2 = 0.5, IDCG = 1/log2(1+1) = 1.0 -> nDCG = 0.5
    assert math.isclose(worse, 0.5, rel_tol=1e-9)


def test_accumulator_averages_across_queries() -> None:
    acc = RetrievalMetricsAccumulator(k=2)
    acc.add(["a", "b"], {"a"})  # hit, precision 0.5
    acc.add(["x", "y"], {"z"})  # miss, precision 0.0
    summary = acc.summary()
    assert summary["n"] == 2
    assert summary["hit_at_2"] == 0.5
    assert summary["precision_at_2"] == 0.25
