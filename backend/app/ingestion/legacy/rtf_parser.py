""".rtf via striprtf — lightweight, pure-Python, no LibreOffice dependency."""

from __future__ import annotations

from pathlib import Path

from striprtf.striprtf import rtf_to_text

from app.ingestion.parsers.base import ParsedDocument


class RtfParser:
    def parse(self, path: Path) -> ParsedDocument:
        raw = path.read_text(encoding="utf-8", errors="replace")
        text = rtf_to_text(raw)
        return ParsedDocument(text=text, metadata={"parser": "striprtf"})
