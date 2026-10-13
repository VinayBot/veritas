"""Document profiling: every feature below is computed from the document's real masked text
and the real graph built at ingestion. Nothing is estimated from metadata, with one stated
exception: `pages_estimated`, a heuristic used only when the parser reported no page count
(plain text has no pages).

`document_type` is the single feature that comes from a language model's opinion. It is shown
for context, and no recommendation rule depends on it.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from pydantic import BaseModel

from app.chunking.strategies._sentences import split_sentences
from app.chunking.tokenization import TokenCounter
from app.graphrag.extractor import extract_entities
from app.llm.client import LlmUnavailableError, complete
from app.stores.graph.networkx_store import get_graph_store

DOCUMENT_TYPES = ("legal", "policy", "research", "faq", "manual", "web_article", "mixed")
_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_LIST_ITEM_RE = re.compile(r"^\s*([-*]|\d+\.)\s", re.MULTILINE)
_CODE_LINE_RE = re.compile(r"^(```|    \S)", re.MULTILINE)
_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z'-]+")

# Phrases by which a document points at another part of itself.
_CROSS_REFERENCE_RE = re.compile(
    r"\b(?:see|refer to|as (?:described|defined|noted|outlined|stated|set out|specified) in|"
    r"pursuant to|in accordance with|subject to|under)\s+"
    r"(?:the\s+)?(?:section|clause|article|chapter|appendix|annex|table|figure|paragraph|part|"
    r"schedule|exhibit)\s+[\dA-Z][\w.-]*"
    r"|\b(?:section|clause|article|appendix|annex|schedule|exhibit)\s+\d+(?:\.\d+)*\b"
    r"|\b(?:above|below|aforementioned|hereinafter|as mentioned (?:above|earlier|previously))\b",
    re.IGNORECASE,
)

# Entity text is NER-scanned at most this far; documents longer than this are sampled and say so.
ENTITY_SCAN_CHARS = 120_000
LEXICAL_WINDOW = 1_000

_DOC_TYPE_PROMPT = (
    "Read this excerpt and classify the document type. Reply with exactly one of: "
    "{types}\n\nExcerpt:\n{sample}\n\nType:"
)


class DocumentProfile(BaseModel):
    document_id: str
    tokens: int
    characters: int = 0
    """Reported by the parser where the format has pages; None otherwise."""
    page_count: int | None = None
    """tokens // 500 — a heuristic, used only when page_count is None."""
    pages_estimated: int
    language: str | None
    heading_density: float
    table_ratio: float
    list_ratio: float
    code_ratio: float
    """prose | tabular | slide_like | mixed — decided by fixed thresholds on the ratios above."""
    content_class: str = "mixed"
    avg_sentence_length: float
    avg_paragraph_length: float
    duplication_ratio: float
    """Distinct words / words, averaged over 1,000-word windows so length does not bias it."""
    lexical_diversity: float = 0.0
    ocr_confidence: float | None
    """True when OCR confidence was reported and is low enough to distrust the text."""
    low_quality_scan: bool = False
    """Entity mentions per 1,000 tokens."""
    entity_density: float
    """Distinct entities per 1,000 tokens."""
    unique_entity_density: float = 0.0
    unique_entities: int = 0
    """How many different kinds of entity appear (people, organisations, dates, ...)."""
    entity_types: int = 0
    """Shannon entropy of the entity-type distribution, in bits: 0 = all one type."""
    entity_type_spread: float = 0.0
    """False when the document was longer than the NER scan limit and only the start was read."""
    entities_fully_scanned: bool = True
    relation_density: float
    """How many times the document refers to another part of itself."""
    cross_references: int = 0
    """Cross-references per 1,000 tokens."""
    cross_reference_density: float = 0.0
    document_type: str


def _line_ratio(pattern: re.Pattern, text: str, total_lines: int) -> float:
    if total_lines == 0:
        return 0.0
    return len(pattern.findall(text)) / total_lines


def _avg_words(parts: list[str]) -> float:
    if not parts:
        return 0.0
    word_counts = [len(p.split()) for p in parts if p.strip()]
    return sum(word_counts) / len(word_counts) if word_counts else 0.0


def _duplication_ratio(text: str) -> float:
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) < 2:
        return 0.0
    seen_shingle_sets: list[set[str]] = []
    duplicates = 0
    for para in paragraphs:
        shingles = {para[i : i + 8] for i in range(max(len(para) - 8, 1))} or {para}
        is_dup = any(
            len(shingles & other) / max(min(len(shingles), len(other)), 1) >= 0.8
            for other in seen_shingle_sets
        )
        if is_dup:
            duplicates += 1
        else:
            seen_shingle_sets.append(shingles)
    return duplicates / len(paragraphs)


def lexical_diversity(text: str) -> float:
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if not words:
        return 0.0
    windows = [words[i : i + LEXICAL_WINDOW] for i in range(0, len(words), LEXICAL_WINDOW)]
    # A short trailing window would score artificially high; fold it out unless it is all there is.
    if len(windows) > 1 and len(windows[-1]) < LEXICAL_WINDOW // 2:
        windows = windows[:-1]
    return sum(len(set(w)) / len(w) for w in windows) / len(windows)


def content_class(
    table_ratio: float, list_ratio: float, heading_density: float, avg_paragraph_words: float
) -> str:
    if table_ratio >= 0.25:
        return "tabular"
    if heading_density >= 0.12 and avg_paragraph_words < 25:
        return "slide_like"
    if table_ratio < 0.05 and list_ratio < 0.2 and avg_paragraph_words >= 30:
        return "prose"
    return "mixed"


def _entropy(counts: Counter) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum((n / total) * math.log2(n / total) for n in counts.values() if n)


async def _guess_document_type(sample: str) -> str:
    try:
        raw = await complete(
            _DOC_TYPE_PROMPT.format(types=", ".join(DOCUMENT_TYPES), sample=sample[:2000]),
            max_tokens=10,
            temperature=0.0,
        )
    except LlmUnavailableError:
        return "mixed"
    cleaned = raw.strip().lower().replace(" ", "_")
    for t in DOCUMENT_TYPES:
        if t in cleaned:
            return t
    return "mixed"


async def profile_document(
    document_id: str,
    text: str,
    language: str | None,
    ocr_confidence: float | None,
    page_count: int | None = None,
) -> DocumentProfile:
    lines = text.split("\n")
    total_lines = max(len(lines), 1)
    tokens = TokenCounter().count(text)
    per_k = 1000 / max(tokens, 1)

    sentences = split_sentences(text)
    paragraphs = [p for p in text.split("\n\n") if p.strip()]
    avg_paragraph = _avg_words(paragraphs)

    scanned = text[:ENTITY_SCAN_CHARS]
    entities = extract_entities(scanned)
    # Density is per token of the text actually scanned, so a sampled document is not diluted.
    scanned_tokens = tokens if len(text) <= ENTITY_SCAN_CHARS else TokenCounter().count(scanned)
    scan_per_k = 1000 / max(scanned_tokens, 1)
    unique = {(e.label, e.text.strip().lower()) for e in entities}
    type_counts = Counter(label for label, _ in unique)

    graph_data = get_graph_store().to_json(doc_id=document_id)
    cross_refs = len(_CROSS_REFERENCE_RE.findall(text))

    heading_density = _line_ratio(_HEADING_RE, text, total_lines)
    table_ratio = _line_ratio(_TABLE_ROW_RE, text, total_lines)
    list_ratio = _line_ratio(_LIST_ITEM_RE, text, total_lines)

    return DocumentProfile(
        document_id=document_id,
        tokens=tokens,
        characters=len(text),
        page_count=page_count,
        pages_estimated=max(1, tokens // 500),
        language=language,
        heading_density=heading_density,
        table_ratio=table_ratio,
        list_ratio=list_ratio,
        code_ratio=_line_ratio(_CODE_LINE_RE, text, total_lines),
        content_class=content_class(table_ratio, list_ratio, heading_density, avg_paragraph),
        avg_sentence_length=_avg_words(sentences),
        avg_paragraph_length=avg_paragraph,
        duplication_ratio=_duplication_ratio(text),
        lexical_diversity=lexical_diversity(text),
        ocr_confidence=ocr_confidence,
        low_quality_scan=ocr_confidence is not None and ocr_confidence < 0.8,
        entity_density=len(entities) * scan_per_k,
        unique_entity_density=len(unique) * scan_per_k,
        unique_entities=len(unique),
        entity_types=len(type_counts),
        entity_type_spread=_entropy(type_counts),
        entities_fully_scanned=len(text) <= ENTITY_SCAN_CHARS,
        relation_density=len(graph_data["edges"]) * per_k,
        cross_references=cross_refs,
        cross_reference_density=cross_refs * per_k,
        document_type=await _guess_document_type(text),
    )
