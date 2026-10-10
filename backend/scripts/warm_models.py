#!/usr/bin/env python3
"""`make models`. Downloads and verifies every model Veritas needs (Docling's layout/table
models, the spaCy model Presidio uses, the sentence-transformers embedder, the cross-encoder
reranker) plus Ollama reachability and a real vector-store write — the exact same checks the
server runs non-blocking at startup (app/core/preflight.py), run here standalone so the ~4
minute cold-cache cost (see docs/TROUBLESHOOTING.md) is paid once, upfront, deliberately —
not by the first user's upload.
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from app.core.preflight import run_preflight  # noqa: E402


async def main() -> int:
    print("Warming models and checking dependencies (first run can take several minutes)...\n")
    report = await run_preflight()
    for check in report.checks:
        status = "OK  " if check.ok else "FAIL"
        print(f"[{status}] {check.name:<16} {check.duration_ms:>8.0f}ms  {check.detail}")
    print()
    if report.all_ok:
        print("PASS — every model is warmed and every dependency is reachable.")
    else:
        print("FAIL — see the checks above. The server will still boot, but that failing")
        print("check will likely surface again on a user's first request.")
    return 0 if report.all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
