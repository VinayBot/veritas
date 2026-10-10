from __future__ import annotations

import pytest

from app.ingestion.parsers.base import UnsupportedFormatError
from app.ingestion.registry import get_parser, parse_file, supported_extensions


def test_supported_extensions_cover_the_brief() -> None:
    exts = supported_extensions()
    for required in (".pdf", ".docx", ".pptx", ".html", ".md", ".txt", ".csv", ".eml", ".rtf"):
        assert required in exts


def test_unknown_extension_raises() -> None:
    with pytest.raises(UnsupportedFormatError):
        get_parser(".exe")


def test_text_parser_round_trip(tmp_path) -> None:
    path = tmp_path / "note.txt"
    path.write_text("hello world", encoding="utf-8")
    parsed = parse_file(path)
    assert parsed.text == "hello world"


def test_csv_parser_renders_markdown_table(tmp_path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("name,age\nAda,36\nAlan,41\n", encoding="utf-8")
    parsed = parse_file(path)
    assert "| name | age |" in parsed.text
    assert "| Ada | 36 |" in parsed.text


def test_eml_parser_extracts_headers_and_body(tmp_path) -> None:
    raw = (
        "From: alice@example.com\n"
        "To: bob@example.com\n"
        "Subject: Hello\n"
        "Date: Mon, 1 Jan 2024 00:00:00 +0000\n"
        "Content-Type: text/plain\n\n"
        "This is the body of the email."
    )
    path = tmp_path / "msg.eml"
    path.write_bytes(raw.encode("utf-8"))
    parsed = parse_file(path)
    assert "alice@example.com" in parsed.text
    assert "This is the body of the email." in parsed.text
