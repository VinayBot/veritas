"""Layout-aware parsing for PDF, DOCX, PPTX and scanned images via Docling.

Docling preserves reading order, converts tables to Markdown, and keeps headings — this is
what the refiner and structure-aware chunking strategy (Phase 3) depend on.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from app.core.inference_lock import run_exclusive
from app.ingestion.parsers.base import ParsedDocument, ParseError

if TYPE_CHECKING:
    from docling.document_converter import DocumentConverter


class DoclingParser:
    def __init__(self) -> None:
        self._converter: DocumentConverter | None = None

    def _get_converter(self) -> DocumentConverter:
        if self._converter is None:
            from docling.document_converter import DocumentConverter

            self._converter = DocumentConverter()
        return self._converter

    def parse(self, path: Path) -> ParsedDocument:
        converter = self._get_converter()
        try:
            result = run_exclusive(converter.convert, str(path))
        except Exception as exc:
            # Docling's own exception for every one of these cases (empty, corrupt, or
            # password-protected) is the same unhelpful, internal-hash-bearing message —
            # see docs/TROUBLESHOOTING.md — so there's no reliable way to name the specific
            # cause; give an honest, actionable message covering the real set instead.
            raise ParseError(
                f"Could not read '{path.name}' as a document. It may be empty, corrupt, or "
                "password-protected — try re-exporting it (or removing the password) and "
                "uploading again."
            ) from exc
        doc = result.document
        text = doc.export_to_markdown()
        num_pages = len(getattr(doc, "pages", None) or []) or None

        ocr_confidence = None
        try:
            confidences = [
                page.assembled.ocr_confidence
                for page in getattr(doc, "pages", {}).values()
                if getattr(page, "assembled", None) is not None
                and getattr(page.assembled, "ocr_confidence", None) is not None
            ]
            if confidences:
                ocr_confidence = sum(confidences) / len(confidences)
        except AttributeError:
            ocr_confidence = None

        return ParsedDocument(
            text=text,
            metadata={"parser": "docling"},
            pages=num_pages,
            ocr_confidence=ocr_confidence,
        )
