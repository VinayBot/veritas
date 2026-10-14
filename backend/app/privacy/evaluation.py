"""Precision and recall of PII detection against a hand-labelled set
(tests/fixtures/pii_eval.json): every value that must be masked, and look-alikes that must not
be. Matching is per entity type on the exact value, after the same overlap resolution the
ingestion pipeline applies. Run with `make pii-eval`; a test keeps the scores above a floor."""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.privacy.detector import detect
from app.privacy.service import _drop_overlaps

EVAL_SET = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "pii_eval.json"


def _norm(value: str) -> str:
    value = value.strip()
    return value[:-2] if value.endswith(("'s", "’s")) else value


@dataclass
class TypeScore:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


@dataclass
class PiiEvalReport:
    by_type: dict[str, TypeScore] = field(default_factory=lambda: defaultdict(TypeScore))
    errors: list[str] = field(default_factory=list)
    cases: int = 0

    @property
    def overall(self) -> TypeScore:
        total = TypeScore()
        for score in self.by_type.values():
            total.tp += score.tp
            total.fp += score.fp
            total.fn += score.fn
        return total


def evaluate(path: Path = EVAL_SET) -> PiiEvalReport:
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    report = PiiEvalReport(cases=len(cases))
    for case in cases:
        gold = {(t, _norm(v)) for t, v in case["pii"]}
        found = {
            (e.entity_type, _norm(e.text))
            for e in _drop_overlaps(detect(case["text"], case.get("language", "en")))
        }
        for item in found & gold:
            report.by_type[item[0]].tp += 1
        for item in found - gold:
            report.by_type[item[0]].fp += 1
            report.errors.append(f"false positive {item} in {case['text']!r}")
        for item in gold - found:
            report.by_type[item[0]].fn += 1
            report.errors.append(f"missed {item} in {case['text']!r}")
    return report


def render(report: PiiEvalReport) -> str:
    lines = [
        f"PII detection on {report.cases} labelled sentences",
        f"{'Type':<15} {'TP':>3} {'FP':>3} {'FN':>3} {'Precision':>9} {'Recall':>7} {'F1':>5}",
    ]
    rows = [*sorted(report.by_type.items()), ("ALL", report.overall)]
    for name, sc in rows:
        counts = f"{sc.tp:>3} {sc.fp:>3} {sc.fn:>3}"
        lines.append(f"{name:<15} {counts} {sc.precision:>9.2f} {sc.recall:>7.2f} {sc.f1:>5.2f}")
    return "\n".join(lines)
