"""Real token counting via the actual embedding model's tokenizer — chunk sizes (128/256/512/
1024) are token counts, not characters or words, so this has to be the real tokenizer, not an
approximation.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.core.config import get_settings


@lru_cache(maxsize=4)
def _get_tokenizer(model_name: str):
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(model_name)


class TokenCounter:
    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or get_settings().embedding_model
        self._tokenizer = _get_tokenizer(self.model_name)

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._tokenizer.encode(text, add_special_tokens=False))

    def encode(self, text: str) -> list[int]:
        return self._tokenizer.encode(text, add_special_tokens=False)

    def decode(self, ids: list[int]) -> str:
        """Lossy for chunk text: this embedding model's tokenizer is uncased and splits
        punctuation, so a decode round-trip lowercases and re-spaces it ("<PERSON_b43251>"
        comes back as "< person _ b43251 >"). Chunk text is cut from the original with
        `offsets`, `tail` and `span` instead."""
        return self._tokenizer.decode(ids)

    def offsets(self, text: str) -> list[tuple[int, int]]:
        """Character span of each token in `text`."""
        if not text:
            return []
        encoded = self._tokenizer(text, add_special_tokens=False, return_offsets_mapping=True)
        return [(int(a), int(b)) for a, b in encoded["offset_mapping"]]

    def tail(self, text: str, n_tokens: int) -> str:
        """The last `n_tokens` tokens of `text`, as the original characters."""
        offsets = self.offsets(text)
        if n_tokens <= 0 or not offsets:
            return ""
        if n_tokens >= len(offsets):
            return text
        return text[snap_start(text, offsets[-n_tokens][0]) :]

    def span(self, text: str, offsets: list[tuple[int, int]], start: int, end: int) -> str:
        """Tokens [start, end) of `text` (offsets from `self.offsets(text)`), as the original
        characters."""
        end = min(end, len(offsets))
        if start >= end:
            return ""
        return text[snap_start(text, offsets[start][0]) : snap_end(text, offsets[end - 1][1])]


# A masked value such as <PERSON_b43251> must never be cut in two: half a token is neither
# the masked value nor readable text, and the detector then reads the hex part as a name.
_MASK_TOKEN_RE = re.compile(r"<[A-Z][A-Z_]*_[0-9a-f]{6,}>")


def snap_start(text: str, pos: int) -> int:
    for match in _MASK_TOKEN_RE.finditer(text):
        if match.start() < pos < match.end():
            return match.start()
    return pos


def snap_end(text: str, pos: int) -> int:
    for match in _MASK_TOKEN_RE.finditer(text):
        if match.start() < pos < match.end():
            return match.end()
    return pos
