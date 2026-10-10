from __future__ import annotations

from app.ingestion.refiner import refine


def test_quality_improves_on_messy_text() -> None:
    messy = (
        "This is a sen-\ntence that was broken.\n"
        + "Page 3\n" * 1
        + "Click here to accept cookies\n"
        + ("Confidential Footer\n" * 4)
        + "This is a sen-\ntence that was broken.\n"
    )
    result = refine(messy)
    assert result.quality_after >= result.quality_before
    fix_types = {f["type"] for f in result.fix_log}
    assert "dehyphenation" in fix_types
    assert "sen tence" not in result.text
    assert "sentence" in result.text
    assert "Confidential Footer" not in result.text
    assert "Click here to accept cookies" not in result.text


def test_near_duplicate_paragraphs_removed() -> None:
    para = (
        "The quarterly report shows revenue increased significantly across all regions this year."
    )
    text = f"{para}\n\n{para}\n\nSomething entirely different and unrelated to the above paragraph."
    result = refine(text)
    assert result.text.count("quarterly report") == 1
    assert result.duplication_ratio > 0


def test_language_detection() -> None:
    result = refine("This is a reasonably long piece of English text for language detection.")
    assert result.language == "en"


def test_empty_text_scores_zero() -> None:
    result = refine("")
    assert result.quality_before == 0.0
    assert result.quality_after == 0.0
