"""Real token counting via the actual embedding model's tokenizer — chunk sizes (128/256/512/
1024) are token counts, not characters or words, so this has to be the real tokenizer, not an
approximation.
"""

from __future__ import annotations

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
        return self._tokenizer.decode(ids)
