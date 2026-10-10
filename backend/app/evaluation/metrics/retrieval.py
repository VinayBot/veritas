"""Standard retrieval metrics, computed from real retrieved-chunk-ID lists against real
ground-truth chunk IDs — no approximations, these are the textbook formulas.
"""

from __future__ import annotations


def precision_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    hits = sum(1 for c in top_k if c in relevant)
    return hits / len(top_k)


def recall_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for c in top_k if c in relevant)
    return hits / len(relevant)


def hit_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    top_k = retrieved[:k]
    return 1.0 if any(c in relevant for c in top_k) else 0.0


def reciprocal_rank(retrieved: list[str], relevant: set[str]) -> float:
    for i, chunk_id in enumerate(retrieved):
        if chunk_id in relevant:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int) -> float:
    import math

    top_k = retrieved[:k]
    dcg = sum(1.0 / math.log2(i + 2) for i, c in enumerate(top_k) if c in relevant)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg > 0 else 0.0


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class RetrievalMetricsAccumulator:
    """Averages per-query metrics across a whole evaluation run."""

    def __init__(self, k: int = 5) -> None:
        self.k = k
        self._precision: list[float] = []
        self._recall: list[float] = []
        self._hit: list[float] = []
        self._rr: list[float] = []
        self._ndcg: list[float] = []

    def add(self, retrieved: list[str], relevant: set[str]) -> None:
        self._precision.append(precision_at_k(retrieved, relevant, self.k))
        self._recall.append(recall_at_k(retrieved, relevant, self.k))
        self._hit.append(hit_at_k(retrieved, relevant, self.k))
        self._rr.append(reciprocal_rank(retrieved, relevant))
        self._ndcg.append(ndcg_at_k(retrieved, relevant, self.k))

    def summary(self) -> dict[str, float]:
        return {
            f"precision_at_{self.k}": mean(self._precision),
            f"recall_at_{self.k}": mean(self._recall),
            f"hit_at_{self.k}": mean(self._hit),
            "mrr": mean(self._rr),
            f"ndcg_at_{self.k}": mean(self._ndcg),
            "n": len(self._precision),
        }
