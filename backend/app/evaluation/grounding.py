"""Sentence-level grounding: which sentences of an answer the retrieved text supports.

One model call lists the sentences it could not find support for; two deterministic checks
then keep that list honest (both reproduced as real model slips — see
docs/TROUBLESHOOTING.md): a "finding" that is not actually a sentence of the answer is
discarded, and a sentence that appears nearly verbatim in the context is treated as
supported whatever the model said.

Used by the agent's verifier to decide whether to revise, and after every answer to show
the reader exactly which sentences are unsupported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.chunking.strategies._sentences import split_sentences
from app.llm.client import LlmUnavailableError, complete
from app.llm.json_utils import extract_json_array

VERIFY_PROMPT = (
    "Context:\n{context}\n\nAnswer to check:\n{answer}\n\n"
    "List any sentences in the answer that are NOT directly supported by the context, as a "
    "JSON array of strings (the exact unsupported sentences, copied verbatim). If every "
    "sentence is supported, return []. Return ONLY the JSON array, no other text."
)

_WORD_RE = re.compile(r"[a-z0-9]+")
_CITATION_RE = re.compile(r"\[\d+\]")


def _words(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _squash(text: str) -> str:
    return " ".join(_CITATION_RE.sub("", text).lower().split())


def is_claim_in_answer(claim: str, answer: str) -> bool:
    """A real finding names a sentence that is actually in the answer. Near-verbatim counts
    (whitespace and punctuation drift); something sharing almost no words with the answer is
    the model echoing the context back, not a finding."""
    if _squash(claim) and _squash(claim) in _squash(answer):
        return True
    claim_words = _words(claim)
    if not claim_words:
        return False
    return len(claim_words & _words(answer)) / len(claim_words) >= 0.7


def is_claim_in_context(claim: str, context: str) -> bool:
    """A sentence quoted (near-)verbatim from the context is supported by definition. The bar
    is higher than is_claim_in_answer (0.9 vs 0.7) because this overrides a verdict the model
    actually reached."""
    if _squash(claim) and _squash(claim) in _squash(context):
        return True
    claim_words = _words(claim)
    if not claim_words:
        return False
    return len(claim_words & _words(context)) / len(claim_words) >= 0.9


async def unsupported_claims(
    answer: str, context: str, model: str | None = None
) -> list[str] | None:
    """Sentences of `answer` with no support in `context`. None means the check could not
    run (model unavailable) — distinct from an empty list, which means everything held up."""
    try:
        raw = await complete(
            VERIFY_PROMPT.format(context=context, answer=answer),
            model=model,
            max_tokens=400,
            temperature=0.0,
        )
    except LlmUnavailableError:
        return None
    claims = [str(c) for c in (extract_json_array(raw) or []) if isinstance(c, str)]
    claims = [c for c in claims if is_claim_in_answer(c, answer)]
    return [c for c in claims if not is_claim_in_context(c, context)]


@dataclass
class GroundingReport:
    """`score` is supported sentences / checked sentences."""

    score: float
    sentences: list[dict]
    supported: int
    total: int

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "sentences": self.sentences,
            "supported": self.supported,
            "total": self.total,
        }


def _matches(sentence: str, claims: list[str]) -> bool:
    squashed = _squash(sentence)
    sentence_words = _words(sentence)
    for claim in claims:
        claim_squashed = _squash(claim)
        if claim_squashed and (claim_squashed in squashed or squashed in claim_squashed):
            return True
        claim_words = _words(claim)
        if claim_words and sentence_words:
            overlap = len(claim_words & sentence_words) / min(len(claim_words), len(sentence_words))
            if overlap >= 0.8:
                return True
    return False


async def ground_answer(
    answer: str, context: str, model: str | None = None
) -> GroundingReport | None:
    """Per-sentence support for an answer. None when it could not be measured, or when the
    answer makes no checkable claim (an abstention, an empty answer)."""
    from app.evaluation.judge import is_abstention

    sentences = [s.strip() for s in split_sentences(answer) if len(_words(s)) >= 3]
    if not sentences or is_abstention(answer) or not context.strip():
        return None
    claims = await unsupported_claims(answer, context, model=model)
    if claims is None:
        return None
    marked = [{"text": s, "supported": not _matches(s, claims)} for s in sentences]
    supported = sum(1 for m in marked if m["supported"])
    return GroundingReport(
        score=supported / len(marked), sentences=marked, supported=supported, total=len(marked)
    )
