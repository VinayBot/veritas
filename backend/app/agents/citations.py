"""Citation markers in an answer: "[2]", and the grouped form small models also write,
"[7, 8]" or "[3,5,6]". Every place that reads markers goes through here, so a grouped
citation is never mistaken for no citation at all."""

from __future__ import annotations

import re

# One bracket holding one or more numbers separated by commas.
MARKER_GROUP_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def citation_markers(text: str) -> list[int]:
    """Every cited number, in order, duplicates kept."""
    return [int(n) for group in MARKER_GROUP_RE.findall(text) for n in group.split(",")]
