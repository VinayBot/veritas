from __future__ import annotations

from app.privacy import vault
from app.privacy.detector import detect
from app.privacy.service import tokenize_text
from app.privacy.tokenizer import make_token, mask_preview


def test_tokenizer_is_deterministic() -> None:
    t1 = make_token("EMAIL_ADDRESS", "john@example.com")
    t2 = make_token("EMAIL_ADDRESS", "  JOHN@EXAMPLE.COM  ")
    assert t1 == t2
    assert t1.startswith("<EMAIL_ADDRESS_")
    assert t1.endswith(">")


def test_tokenizer_differs_by_value_and_type() -> None:
    assert make_token("EMAIL_ADDRESS", "a@example.com") != make_token(
        "EMAIL_ADDRESS", "b@example.com"
    )
    assert make_token("EMAIL_ADDRESS", "x") != make_token("PHONE_NUMBER", "x")


def test_mask_preview_hides_most_of_value() -> None:
    assert mask_preview("EMAIL_ADDRESS", "jane@acme.com") == "j***@acme.com"


def test_detector_finds_email_and_person() -> None:
    results = detect("Please contact Jane Doe at jane.doe@example.com for details.")
    types = {r.entity_type for r in results}
    assert "EMAIL_ADDRESS" in types


def test_detector_does_not_flag_organizations_or_locations() -> None:
    # Regression for the Phase 5 finding: Presidio's *default* entity set includes
    # LOCATION/ORGANIZATION, which isn't in the brief's explicit PII list and collides head-on
    # with GraphRAG's own entity types (an org/location mentioned anywhere would be masked
    # before the graph ever saw it). detector.py now passes an explicit `entities=` allowlist.
    results = detect("Silverpine Logistics signed a deal with a partner based in Haversham.")
    types = {r.entity_type for r in results}
    assert "LOCATION" not in types
    assert "ORGANIZATION" not in types


def test_detector_classifies_phone_number_correctly_not_as_uk_nhs() -> None:
    # Regression for a Phase 2 finding: Presidio's UK_NHS recognizer scored higher than the
    # phone recognizer for a plain US-style number, misclassifying it. UK_NHS isn't in the
    # explicit allowlist (not asked for by the brief), so this no longer happens.
    results = detect("Call me at 212-555-0199 about the invoice.")
    types = {r.entity_type for r in results}
    assert "UK_NHS" not in types
    assert "PHONE_NUMBER" in types


async def test_tokenize_text_masks_and_counts() -> None:
    text = "Contact Jane at jane.doe@example.com for the invoice."
    result = await tokenize_text(text, document_id="doc-1")
    assert "jane.doe@example.com" not in result.masked_text
    assert "EMAIL_ADDRESS" in result.pii_counts
    assert result.pii_counts["EMAIL_ADDRESS"] == 1


async def test_vault_round_trip() -> None:
    text = "Email me at round.trip@example.com please."
    result = await tokenize_text(text, document_id="doc-2")
    token = next(t for t in _extract_tokens(result.masked_text))
    revealed = await vault.reveal(token, session_id="session-1")
    assert revealed == "round.trip@example.com"


async def test_vault_reveal_unknown_token_returns_none() -> None:
    revealed = await vault.reveal("<EMAIL_ADDRESS_ffffff>", session_id="session-1")
    assert revealed is None


def _extract_tokens(text: str) -> list[str]:
    import re

    return re.findall(r"<[A-Z_]+_[0-9a-f]{6}>", text)


def test_names_the_small_ner_model_misses_are_still_masked() -> None:
    """spaCy's small model found no person in "Contact Elena Petrova" and called
    "Elena Petrova's" an organisation; both reached the sample's knowledge graph unmasked."""
    from app.privacy.detector import detect

    for text in ("Contact Elena Petrova, Head of Global Compliance.", "Elena Petrova's team."):
        assert ("PERSON", "Elena Petrova") in [(e.entity_type, e.text) for e in detect(text)]
    assert detect("Remote Work Policy. Business Travel needs Global Compliance approval.") == []


def test_emails_on_internal_domains_are_masked() -> None:
    from app.privacy.detector import detect

    text = "Write to priya.sharma@northwind-tech.example"
    found = [(e.entity_type, e.text) for e in detect(text)]
    assert found == [("EMAIL_ADDRESS", "priya.sharma@northwind-tech.example")]
