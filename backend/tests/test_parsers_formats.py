"""Every document format the upload accepts, parsed from a real file of that format. Files are
built here with the same libraries a user's office suite writes them with, so nothing is
mocked; the legacy binary formats run whenever LibreOffice is installed (CI installs it)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app.ingestion.parsers.base import UnsupportedFormatError
from app.ingestion.registry import parse_file


def test_docx_keeps_headings_and_table_text(tmp_path) -> None:
    import docx

    document = docx.Document()
    document.add_heading("Remote Work Policy", level=1)
    document.add_paragraph("Employees may work remotely up to three days per week.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Region", "Stipend"
    table.cell(1, 0).text, table.cell(1, 1).text = "EMEA", "500 EUR"
    path = tmp_path / "policy.docx"
    document.save(path)

    text = parse_file(path).text
    assert "Remote Work Policy" in text
    assert "three days per week" in text
    assert "EMEA" in text and "500 EUR" in text


def test_pptx_reads_every_slide(tmp_path) -> None:
    from pptx import Presentation

    deck = Presentation()
    for title, body in [("Quarterly Review", "Revenue grew 12 percent."), ("Risks", "Churn.")]:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
    path = tmp_path / "review.pptx"
    deck.save(path)

    text = parse_file(path).text
    assert "Quarterly Review" in text and "Revenue grew 12 percent" in text
    assert "Risks" in text


def test_xlsx_rows_become_readable_text(tmp_path) -> None:
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Item", "Limit"])
    sheet.append(["Hotel per night", "180 USD"])
    path = tmp_path / "limits.xlsx"
    book.save(path)

    text = parse_file(path).text
    assert "Hotel per night" in text and "180 USD" in text


def test_rtf_control_words_are_stripped(tmp_path) -> None:
    path = tmp_path / "memo.rtf"
    path.write_text(
        r"{\rtf1\ansi{\fonttbl\f0\fswiss Helvetica;}\f0\pard "
        r"Travel must be booked {\b two weeks} in advance.\par}",
        encoding="utf-8",
    )
    text = parse_file(path).text
    assert "Travel must be booked two weeks in advance." in " ".join(text.split())
    assert "\\rtf1" not in text and "fonttbl" not in text


@pytest.mark.parametrize(("suffix", "convert_to"), [(".doc", "doc"), (".xls", "xls")])
def test_legacy_binary_office_files(tmp_path, suffix: str, convert_to: str) -> None:
    """Old binary Word/Excel files: converted with headless LibreOffice and parsed again."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice is None:
        with pytest.raises(UnsupportedFormatError, match="LibreOffice is not installed"):
            parse_file(_dummy(tmp_path, suffix))
        return
    source = tmp_path / ("note.txt" if suffix == ".doc" else "sheet.csv")
    source.write_text(
        "Legacy memo: the archive policy keeps records for seven years.\n"
        if suffix == ".doc"
        else "Item,Limit\nArchive retention,seven years\n",
        encoding="utf-8",
    )
    subprocess.run(
        [soffice, "--headless", "--convert-to", convert_to, "--outdir", str(tmp_path), source],
        check=True,
        capture_output=True,
        timeout=120,
    )
    text = parse_file(source.with_suffix(suffix)).text
    assert "seven years" in text


def _dummy(tmp_path, suffix: str):
    path = tmp_path / f"old{suffix}"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 512)  # OLE2 header
    return path
