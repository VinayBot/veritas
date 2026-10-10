"""Shared "ask the LLM for JSON, parse defensively" helper — every agent node that needs
structured output from a model that has no guaranteed JSON mode (local Ollama models) goes
through this, rather than each node reimplementing the same regex-and-hope parsing.
"""

from __future__ import annotations

import json
import re

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def extract_json_object(raw: str) -> dict | None:
    candidate = raw.strip()
    match = _JSON_OBJECT_RE.search(candidate)
    if match:
        candidate = match.group(0)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def extract_json_array(raw: str) -> list | None:
    candidate = raw.strip()
    match = _JSON_ARRAY_RE.search(candidate)
    if match:
        candidate = match.group(0)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None
