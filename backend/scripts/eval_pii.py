#!/usr/bin/env python3
"""`make pii-eval`: precision and recall of PII detection on the hand-labelled set."""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from app.privacy.evaluation import evaluate, render  # noqa: E402

report = evaluate()
print(render(report))
if report.errors:
    print("\n" + "\n".join(report.errors))
