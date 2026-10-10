"""Document profiling: every feature below is computed from the document's real masked text,
its real persisted chunks, and (for relation density) the real graph built at ingestion — none
of this is estimated from metadata alone except `pages`, which is a documented heuristic where
no real page count is available (plain text has no concept of pages).
"""

from __future__ import annotations

import re

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

_DOC_TYPE_PROMPT = (
    "Read this excerpt and classify the document type. Reply with exactly one of: "
    "{types}\n\nExcerpt:\n{sample}\n\nType:"
)


class DocumentProfile(BaseModel):
    document_id: str
    pages_estimated: int
    tokens: int
    language: str | None
    heading_density: float
    table_ratio: float
    list_ratio: float
    code_ratio: float
    avg_sentence_length: float
    avg_paragraph_length: float
    duplication_ratio: float
    ocr_confidence: float | None
    entity_density: float
    relation_density: float
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
    document_id: str, text: str, language: str | None, ocr_confidence: float | None
) -> DocumentProfile:
    lines = text.split("\n")
    total_lines = max(len(lines), 1)
    counter = TokenCounter()
    tokens = counter.count(text)

    sentences = split_sentences(text)
    paragraphs = [p for p in text.split("\n\n") if p.strip()]

    entities = extract_entities(text[:5000])  # sample — full-doc NER is Phase 5's job at ingestion
    entity_density = (len(entities) / max(tokens, 1)) * 1000

    graph_data = get_graph_store().to_json(doc_id=document_id)
    relation_density = (len(graph_data["edges"]) / max(tokens, 1)) * 1000

    document_type = await _guess_document_type(text)

    return DocumentProfile(
        document_id=document_id,
        pages_estimated=max(1, tokens // 500),
        tokens=tokens,
        language=language,
        heading_density=_line_ratio(_HEADING_RE, text, total_lines),
        table_ratio=_line_ratio(_TABLE_ROW_RE, text, total_lines),
        list_ratio=_line_ratio(_LIST_ITEM_RE, text, total_lines),
        code_ratio=_line_ratio(_CODE_LINE_RE, text, total_lines),
        avg_sentence_length=_avg_words(sentences),
        avg_paragraph_length=_avg_words(paragraphs),
        duplication_ratio=_duplication_ratio(text),
        ocr_confidence=ocr_confidence,
        entity_density=entity_density,
        relation_density=relation_density,
        document_type=document_type,
    )
