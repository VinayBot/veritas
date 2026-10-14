"""PII detection: Presidio (NER + built-in recognizers) plus a few custom pattern recognizers
Presidio doesn't ship with out of the box (Aadhaar, PAN).

Explicitly configured to use en_core_web_sm rather than Presidio's default en_core_web_lg,
which this environment doesn't have — see docs/DECISIONS.md.
"""

from __future__ import annotations

import re
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


# Presidio's own email recognizer validates the top-level domain, so internal domains
# (".corp", ".local", the reserved ".example") were not masked.
_EMAIL_PATTERN = Pattern(
    name="email_any_domain",
    regex=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b",
    score=0.9,
)
# A lookahead, so candidates overlap: in "Contact Elena Petrova" the pair "Contact Elena" must
# not consume "Elena".
_GIVEN_NAME_RE = re.compile(r"\b(?=([A-Z][a-z]+)\s+([A-Z][a-z]+(?:-[A-Z][a-z]+)?)\b)")


class GivenNameRecognizer(EntityRecognizer):
    """A known given name followed by a capitalised surname is a PERSON. Covers names the
    small spaCy model misses or calls an organisation; see app/privacy/given_names.py."""

    def __init__(self) -> None:
        super().__init__(supported_entities=["PERSON"], name="GivenNameRecognizer")

    def load(self) -> None:
        return None

    def analyze(self, text: str, entities: list[str], nlp_artifacts: object = None) -> list:
        from app.privacy.given_names import GIVEN_NAMES

        if "PERSON" not in entities:
            return []
        return [
            RecognizerResult(
                "PERSON",
                m.start(1),
                m.end(2),
                # Above spaCy's 0.85: Presidio keeps one result per span, the higher scored,
                # and on non-English text spaCy's is discarded afterwards.
                0.9,
            )
            for m in _GIVEN_NAME_RE.finditer(text)
            if m.group(1).lower() in GIVEN_NAMES
        ]


def _recognizer(result: RecognizerResult) -> str:
    return str((result.recognition_metadata or {}).get("recognizer_name", ""))


def _custom_recognizers() -> list[EntityRecognizer]:
    return [
        PatternRecognizer(supported_entity="EMAIL_ADDRESS", patterns=[_EMAIL_PATTERN]),
        GivenNameRecognizer(),
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


# Lowercase words a real full name can contain ("Ludwig van Beethoven", "Ana de Souza").
_NAME_PARTICLES = frozenset("de da di du del della der den van von la le al bin ibn y e".split())


def _plausible_name(span: str) -> bool:
    """A PERSON span has every word capitalised except name particles. The English NER model
    produced spans such as "bénéficie de seize semaines de congé payé" on a French policy, and
    masking them destroyed the facts they stated."""
    words = [w for w in re.split(r"[\s,]+", span.strip()) if w]
    return bool(words) and all(
        w[0].isupper() or not w[0].isalpha() or w.lower() in _NAME_PARTICLES for w in words
    )


def detect(text: str, language: str | None = "en") -> list[DetectedEntity]:
    """`language`: the document's language. The NER model is English; on any other language its
    PERSON guesses are dropped, and names come only from the pattern-based recognizers (given
    names, emails, phone numbers, IDs), which do not depend on the language."""
    if not text.strip():
        return []
    analyzer = _get_analyzer()
    results: list[RecognizerResult] = analyzer.analyze(
        text=text, language="en", entities=list(ALLOWED_ENTITIES)
    )
    english = language in (None, "en")
    results = [
        r
        for r in results
        if r.entity_type != "PERSON"
        or (
            _plausible_name(text[r.start : r.end])
            and (english or _recognizer(r) != "SpacyRecognizer")
        )
    ]
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
