from __future__ import annotations

from app.profiler.features import DOCUMENT_TYPES, profile_document


async def test_profile_detects_structural_features() -> None:
    text = (
        "# Title\n\n"
        "## Section\n\n"
        "- item one\n- item two\n- item three\n\n"
        "| col1 | col2 |\n|---|---|\n| a | b |\n\n"
        "This is an ordinary sentence of prose for the paragraph here."
    )
    profile = await profile_document("doc-1", text, language="en", ocr_confidence=None)
    assert profile.heading_density > 0
    assert profile.list_ratio > 0
    assert profile.table_ratio > 0
    assert profile.document_type in DOCUMENT_TYPES


async def test_profile_handles_plain_prose_with_no_structure() -> None:
    text = "This is just a normal paragraph with no headings, lists, or tables at all in it."
    profile = await profile_document("doc-2", text, language="en", ocr_confidence=0.95)
    assert profile.heading_density == 0.0
    assert profile.table_ratio == 0.0
    assert profile.list_ratio == 0.0
    assert profile.ocr_confidence == 0.95
    assert profile.tokens > 0


async def test_profile_duplication_ratio_detects_repeated_paragraphs() -> None:
    para = (
        "The quarterly report shows steady growth across every region this year without exception."
    )
    text = (
        f"{para}\n\n{para}\n\nSomething totally different here about an unrelated topic entirely."
    )
    profile = await profile_document("doc-3", text, language="en", ocr_confidence=None)
    assert profile.duplication_ratio > 0


async def test_profile_pages_estimate_scales_with_length() -> None:
    short = await profile_document("doc-4", "short text", language="en", ocr_confidence=None)
    long_text = " ".join(["word"] * 3000)
    long = await profile_document("doc-5", long_text, language="en", ocr_confidence=None)
    assert long.pages_estimated > short.pages_estimated
