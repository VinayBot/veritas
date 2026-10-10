"""Orchestrates detect -> tokenize -> vault-store -> masked text. This runs before chunking,
embedding, indexing or any LLM call — nothing downstream ever sees raw PII.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.privacy import vault
from app.privacy.detector import detect
from app.privacy.tokenizer import make_token


@dataclass
class TokenizeResult:
    masked_text: str
    pii_counts: dict[str, int]


def _drop_overlaps(entities: list) -> list:
    """Entities are pre-sorted (start asc, length desc) by detector.detect — keep the first
    (longest) span at each starting position and drop anything that overlaps it."""
    kept = []
    last_end = -1
    for ent in entities:
        if ent.start >= last_end:
            kept.append(ent)
            last_end = ent.end
    return kept


async def tokenize_text(text: str, document_id: str | None = None) -> TokenizeResult:
    entities = _drop_overlaps(detect(text))
    counts: Counter[str] = Counter()

    # Replace right-to-left so earlier spans' indices stay valid as we edit.
    masked = text
    for ent in sorted(entities, key=lambda e: e.start, reverse=True):
        token = make_token(ent.entity_type, ent.text)
        await vault.store(token, ent.entity_type, ent.text, document_id=document_id)
        masked = masked[: ent.start] + token + masked[ent.end :]
        counts[ent.entity_type] += 1

    return TokenizeResult(masked_text=masked, pii_counts=dict(counts))


def tokenize_query_value(entity_type: str, value: str) -> str:
    """So a question containing a raw email/phone matches the indexed tokens (BM25/dense both
    only ever see tokens) — the agent's query-rewrite step tokenizes recognized PII the same
    deterministic way before retrieval."""
    return make_token(entity_type, value)
