"""Legacy binary Office formats (.doc, .xls) via headless LibreOffice.

There is no good pure-Python reader for the old binary (pre-2007) Word/Excel formats, so this
shells out to `soffice --headless --convert-to` and re-parses the result with the parsers we
already have. If LibreOffice isn't installed, this raises a clear, actionable error instead of
silently producing garbage — see docs/DECISIONS.md.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from app.ingestion.parsers.base import ParsedDocument, UnsupportedFormatError
from app.ingestion.parsers.docling_parser import DoclingParser
from app.ingestion.parsers.text_parser import CsvParser

_SOFFICE_CANDIDATES = ("soffice", "libreoffice")


def _find_soffice() -> str | None:
    for name in _SOFFICE_CANDIDATES:
        path = shutil.which(name)
        if path:
            return path
    return None


def _convert(soffice: str, src: Path, target_format: str, outdir: Path) -> Path:
    subprocess.run(
        [soffice, "--headless", "--convert-to", target_format, "--outdir", str(outdir), str(src)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    converted = outdir / f"{src.stem}.{target_format}"
    if not converted.exists():
        raise UnsupportedFormatError(src.suffix, "LibreOffice conversion did not produce output")
    return converted


class LegacyDocParser:
    """.doc -> .docx (via LibreOffice) -> Docling."""

    def parse(self, path: Path) -> ParsedDocument:
        soffice = _find_soffice()
        if not soffice:
            raise UnsupportedFormatError(
                path.suffix,
                "LibreOffice is not installed. Install it (e.g. `brew install libreoffice`) "
                "to enable .doc conversion.",
            )
        with tempfile.TemporaryDirectory() as tmp:
            docx_path = _convert(soffice, path, "docx", Path(tmp))
            parsed = DoclingParser().parse(docx_path)
        parsed.metadata["parser"] = "libreoffice+docling"
        return parsed


class LegacyXlsParser:
    """.xls -> .csv (via LibreOffice) -> the CSV parser."""

    def parse(self, path: Path) -> ParsedDocument:
        soffice = _find_soffice()
        if not soffice:
            raise UnsupportedFormatError(
                path.suffix,
                "LibreOffice is not installed. Install it (e.g. `brew install libreoffice`) "
                "to enable .xls conversion.",
            )
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = _convert(soffice, path, "csv", Path(tmp))
            parsed = CsvParser().parse(csv_path)
        parsed.metadata["parser"] = "libreoffice+csv"
        return parsed
