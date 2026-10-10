"""Parser interface every format-specific parser implements, plus the shared result type."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field


class ParsedDocument(BaseModel):
    text: str
    """Markdown-ish plain text, reading order preserved where the source has structure."""
    metadata: dict[str, Any] = Field(default_factory=dict)
    pages: int | None = None
    ocr_confidence: float | None = None


class Parser(Protocol):
    def parse(self, path: Path) -> ParsedDocument: ...


class UnsupportedFormatError(Exception):
    def __init__(self, extension: str, detail: str = ""):
        self.extension = extension
        message = f"No parser available for '{extension}'" + (f": {detail}" if detail else "")
        super().__init__(message)


class ParseError(Exception):
    """Raised when a parser can't read a file it otherwise supports — empty, corrupt, or
    password-protected. Always carries a clean, human-readable message; parsers must catch
    their underlying library's raw exception and re-raise this instead of letting internal
    details (e.g. Docling's content-hash keys) leak into a user-facing error."""
