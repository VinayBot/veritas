"""Length and encoding checks: zero-width characters (a classic way to hide text from a quick
human skim, or to break up a blocked phrase so a naive substring match misses it) and base64-
looking payloads (which could decode to a hidden instruction).
"""

from __future__ import annotations

import base64
import re

MAX_INPUT_CHARS = 8000
_ZERO_WIDTH_RE = re.compile(r"[​‌‍⁠﻿]")
_BASE64_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")


class EncodingIssue:
    def __init__(self, kind: str, detail: str):
        self.kind = kind
        self.detail = detail


def check(text: str) -> list[EncodingIssue]:
    issues: list[EncodingIssue] = []

    if len(text) > MAX_INPUT_CHARS:
        issues.append(EncodingIssue("too_long", f"{len(text)} chars exceeds {MAX_INPUT_CHARS}"))

    zero_width_count = len(_ZERO_WIDTH_RE.findall(text))
    if zero_width_count:
        issues.append(
            EncodingIssue("zero_width_chars", f"{zero_width_count} zero-width character(s)")
        )

    for match in _BASE64_CANDIDATE_RE.finditer(text):
        candidate = match.group(0)
        try:
            decoded = base64.b64decode(candidate, validate=True).decode("utf-8", errors="strict")
        except Exception:
            continue
        if decoded.isprintable() and len(decoded) > 10:
            issues.append(EncodingIssue("base64_payload", decoded[:200]))

    return issues
