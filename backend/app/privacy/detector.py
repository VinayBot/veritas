"""PII detection: Presidio (NER + built-in recognizers) plus a few custom pattern recognizers
Presidio doesn't ship with out of the box (Aadhaar, PAN).

Explicitly configured to use en_core_web_sm rather than Presidio's default en_core_web_lg,
which this environment doesn't have — see docs/DECISIONS.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from presidio_analyzer import (
    AnalyzerEngine,
    EntityRecognizer,
    Pattern,
    PatternRecognizer,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import NlpEngineProvider

MIN_SCORE = 0.35

# Deliberately narrower than Presidio's default output. Scoped to exactly what Section 1.1 of
# the brief asks for ("international phone formats, national IDs ... IBAN, credit cards,
# emails, names, IPs") rather than Presidio's full default set, which also includes LOCATION,
# ORGANIZATION, NRP, DATE_TIME, URL, UK_NHS, etc. Two concrete problems drove this, not just
# brief-literalism: (1) those extra categories directly collide with GraphRAG's own entity
# types — an org/location mentioned in a document would be masked before the graph ever sees
# it, defeating the knowledge graph for exactly the entities it's supposed to connect; (2) they
# were a real source of the false positives observed in Phase 2 ("Employee Handbook" -> NRP,
# a table header -> PERSON, a phone number -> UK_NHS instead of PHONE_NUMBER). See
# docs/DECISIONS.md for the specific repro that surfaced this.
ALLOWED_ENTITIES = (
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "PERSON",
    "IP_ADDRESS",
    "CREDIT_CARD",
    "IBAN_CODE",
    "US_SSN",
    "AADHAAR",
    "PAN_INDIA",
)

_AADHAAR_PATTERN = Pattern(name="aadhaar", regex=r"\b\d{4}\s?\d{4}\s?\d{4}\b", score=0.55)
_PAN_INDIA_PATTERN = Pattern(name="pan_india", regex=r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", score=0.6)


def _custom_recognizers() -> list[EntityRecognizer]:
    return [
        PatternRecognizer(
            supported_entity="AADHAAR",
            patterns=[_AADHAAR_PATTERN],
            context=["aadhaar", "uidai", "aadhar"],
        ),
        PatternRecognizer(
            supported_entity="PAN_INDIA",
            patterns=[_PAN_INDIA_PATTERN],
            context=["pan", "income tax", "permanent account number"],
        ),
    ]


@dataclass
class DetectedEntity:
    entity_type: str
    start: int
    end: int
    score: float
    text: str


@lru_cache(maxsize=1)
def _get_analyzer() -> AnalyzerEngine:
    config = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
    }
    provider = NlpEngineProvider(nlp_configuration=config)
    nlp_engine = provider.create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
    for recognizer in _custom_recognizers():
        analyzer.registry.add_recognizer(recognizer)
    return analyzer


def detect(text: str, language: str = "en") -> list[DetectedEntity]:
    if not text.strip():
        return []
    analyzer = _get_analyzer()
    results: list[RecognizerResult] = analyzer.analyze(
        text=text, language=language, entities=list(ALLOWED_ENTITIES)
    )
    detected = [
        DetectedEntity(
            entity_type=r.entity_type,
            start=r.start,
            end=r.end,
            score=r.score,
            text=text[r.start : r.end],
        )
        for r in results
        if r.score >= MIN_SCORE
    ]
    # Longer matches first so overlap-resolution (service.py) prefers the more specific span.
    return sorted(detected, key=lambda d: (d.start, -(d.end - d.start)))
