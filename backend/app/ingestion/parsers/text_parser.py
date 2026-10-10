"""Plain-text formats: .txt, .md, .csv. No layout to preserve, just decode."""

from __future__ import annotations

from pathlib import Path

from app.ingestion.parsers.base import ParsedDocument


class TextParser:
    def parse(self, path: Path) -> ParsedDocument:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        return ParsedDocument(text=text, metadata={"parser": "text"})


class CsvParser:
    def parse(self, path: Path) -> ParsedDocument:
        import csv

        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            return ParsedDocument(text="", metadata={"parser": "csv", "rows": 0})

        header, *body = rows
        lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
        lines += ["| " + " | ".join(row) + " |" for row in body]
        return ParsedDocument(text="\n".join(lines), metadata={"parser": "csv", "rows": len(body)})
