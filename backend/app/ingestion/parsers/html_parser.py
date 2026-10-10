"""Raw .html files on disk, via trafilatura (the same extractor the URL scraper uses)."""

from __future__ import annotations

from pathlib import Path

import trafilatura

from app.ingestion.parsers.base import ParsedDocument


class HtmlParser:
    def parse(self, path: Path) -> ParsedDocument:
        raw = path.read_text(encoding="utf-8", errors="replace")
        extracted = trafilatura.extract(raw, output_format="markdown", with_metadata=False)
        return ParsedDocument(text=extracted or "", metadata={"parser": "trafilatura"})
