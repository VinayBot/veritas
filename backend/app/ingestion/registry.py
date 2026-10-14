"""Extension -> parser dispatch. Lazily instantiates parsers (Docling/spaCy are expensive)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.ingestion.legacy.eml_parser import EmlParser
from app.ingestion.legacy.office_legacy import LegacyDocParser, LegacyXlsParser
from app.ingestion.legacy.rtf_parser import RtfParser
from app.ingestion.parsers.base import ParsedDocument, Parser, UnsupportedFormatError
from app.ingestion.parsers.docling_parser import DoclingParser
from app.ingestion.parsers.html_parser import HtmlParser
from app.ingestion.parsers.text_parser import CsvParser, TextParser

_FACTORIES: dict[str, Callable[[], Parser]] = {
    ".pdf": DoclingParser,
    ".docx": DoclingParser,
    ".pptx": DoclingParser,
    ".xlsx": DoclingParser,
    ".png": DoclingParser,
    ".jpg": DoclingParser,
    ".jpeg": DoclingParser,
    ".tiff": DoclingParser,
    ".html": HtmlParser,
    ".htm": HtmlParser,
    ".md": TextParser,
    ".txt": TextParser,
    ".csv": CsvParser,
    ".eml": EmlParser,
    ".rtf": RtfParser,
    ".doc": LegacyDocParser,
    ".xls": LegacyXlsParser,
}

_cache: dict[str, Parser] = {}


def get_parser(extension: str) -> Parser:
    extension = extension.lower()
    if extension not in _FACTORIES:
        raise UnsupportedFormatError(extension)
    if extension not in _cache:
        _cache[extension] = _FACTORIES[extension]()
    return _cache[extension]


def parse_file(path: Path) -> ParsedDocument:
    parser = get_parser(path.suffix)
    return parser.parse(path)


def supported_extensions() -> list[str]:
    return sorted(_FACTORIES.keys())
