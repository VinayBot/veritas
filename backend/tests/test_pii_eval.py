"""PII detection measured on a hand-labelled set in four languages (tests/fixtures/pii_eval.json).
Measured: precision 0.97, recall 1.00 over 31 values and 10 look-alike sentences. The floor
below fails the build if a change makes detection miss or over-mask noticeably."""

from __future__ import annotations

from app.privacy.evaluation import evaluate, render


def test_pii_detection_precision_and_recall_stay_above_the_floor() -> None:
    report = evaluate()
    overall = report.overall
    assert overall.recall >= 0.95, render(report) + "\n" + "\n".join(report.errors)
    assert overall.precision >= 0.9, render(report) + "\n" + "\n".join(report.errors)


def test_every_language_in_the_set_is_covered() -> None:
    import json

    from app.privacy.evaluation import EVAL_SET

    languages = {c["language"] for c in json.loads(EVAL_SET.read_text())["cases"]}
    assert {"en", "fr", "de", "es"} <= languages
