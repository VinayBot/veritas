"""Every chunking strategy implements Chunker and returns a list[Chunk]."""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, Field

_PII_TOKEN_RE = re.compile(r"<[A-Z_]+_[0-9a-f]{6}>")


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    parent_id: str | None = None
    text: str
    page: int | None = None
    section_path: str | None = None
    token_count: int = 0
    pii_token_count: int = 0
    strategy: str = ""
    extra: dict = Field(default_factory=dict)

    def finalize_pii_count(self) -> None:
        self.pii_token_count = len(_PII_TOKEN_RE.findall(self.text))


class Chunker(Protocol):
    name: str

    def chunk(self, doc_id: str, text: str) -> list[Chunk]: ...
