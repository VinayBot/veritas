"""Generates an oversized upload fixture on demand — not committed to git, since any 25MB+
blob of random bytes exercises the same MAX_UPLOAD_BYTES rejection path identically; there's
nothing about its specific bytes worth version-controlling.

Usage: python tests/fixtures/make_oversized.py
"""

from __future__ import annotations

import pathlib

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # backend/app/api/routes/documents.py's real limit
OVERSIZE_MARGIN_BYTES = 5 * 1024 * 1024

OUTPUT = pathlib.Path(__file__).parent / "oversized.pdf"


def main() -> None:
    size = MAX_UPLOAD_BYTES + OVERSIZE_MARGIN_BYTES
    with OUTPUT.open("wb") as f:
        f.write(b"%PDF-1.4\n")  # a token PDF-looking header; the real limit check runs on raw byte length before any parsing, so this is cosmetic, not load-bearing
        f.write(bytes(size))
    print(f"wrote {OUTPUT} ({size:,} bytes, {MAX_UPLOAD_BYTES:,} byte limit)")


if __name__ == "__main__":
    main()
