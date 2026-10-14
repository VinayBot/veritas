"""Statistics that make small evaluation samples honest: bootstrap confidence intervals, and a
judge-free answer score (SQuAD-style token F1 against the known answer)."""

from __future__ import annotations

import random
import re
import string
from collections import Counter
from collections.abc import Sequence

_ARTICLES = re.compile(r"\b(a|an|the)\b", re.I)
_PUNCT = str.maketrans("", "", string.punctuation + "—–’‘“”")
_CITATION = re.compile(r"\[\d+(?:\s*,\s*\d+)*\]")


def bootstrap_ci(
    values: Sequence[float], *, resamples: int = 2000, alpha: float = 0.05, seed: int = 7
) -> tuple[float, float] | None:
    """Percentile bootstrap interval for the mean; None with fewer than two values. Seeded, so
    a report regenerates identically from the same scores."""
    data = [float(v) for v in values]
    if len(data) < 2:
        return None
    rng = random.Random(seed)
    n = len(data)
    means = sorted(sum(rng.choice(data) for _ in range(n)) / n for _ in range(resamples))
    low = means[int(alpha / 2 * resamples)]
    high = means[min(int((1 - alpha / 2) * resamples), resamples - 1)]
    return round(low, 3), round(high, 3)


def _tokens(text: str) -> list[str]:
    text = _CITATION.sub(" ", text.lower()).translate(_PUNCT)
    return _ARTICLES.sub(" ", text).split()


def token_f1(prediction: str, reference: str) -> float:
    """Word-overlap F1 between an answer and the known answer, as in SQuAD. Needs no judge
    model, so it cannot share the judge's biases; it under-credits correct paraphrases, which
    is why it is reported beside the judged correctness, not instead of it."""
    pred, ref = _tokens(prediction), _tokens(reference)
    if not pred or not ref:
        return float(pred == ref)
    common = sum((Counter(pred) & Counter(ref)).values())
    if common == 0:
        return 0.0
    precision, recall = common / len(pred), common / len(ref)
    return 2 * precision * recall / (precision + recall)


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (sx * sy)
