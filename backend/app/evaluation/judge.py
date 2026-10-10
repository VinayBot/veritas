"""LLM-judge: scores generation quality on a 0-1 scale. Used both for the per-answer report
(reference-free -> labelled "Estimated") and the benchmark runner (against synthetic-dataset
ground truth -> labelled "Verified") — same scoring functions either way; the caller decides
the label based on whether a ground-truth answer was available, not this module.
"""

from __future__ import annotations

import re

from app.llm.client import LlmUnavailableError, complete

_SCORE_RE = re.compile(r"\d+(?:\.\d+)?")

_FAITHFULNESS_PROMPT = (
    "Context:\n{context}\n\nAnswer:\n{answer}\n\n"
    "On a scale from 0 to 10, how well is every claim in the answer directly supported by "
    "the context? 10 means every claim is explicitly supported; 0 means none of it is "
    "supported or it contradicts the context. Reply with ONLY the number."
)

_RELEVANCY_PROMPT = (
    "Question: {question}\n\nAnswer: {answer}\n\n"
    "On a scale from 0 to 10, how directly and completely does the answer address the "
    "question (regardless of whether it is factually correct)? Reply with ONLY the number."
)

_CORRECTNESS_PROMPT = (
    "Question: {question}\n\nGround truth answer: {ground_truth}\n\nGiven answer: {answer}\n\n"
    "On a scale from 0 to 10, how semantically consistent is the given answer with the ground "
    "truth answer (same meaning, not necessarily identical wording)? Reply with ONLY the number."
)

_ABSTENTION_PHRASES = (
    "don't have enough",
    "do not have enough",
    "unable to generate",
    "can't help with that",
    "cannot help with that",
    "not enough reliably",
)

_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")


async def _score_0_to_10(prompt: str, fallback: float = 0.5) -> float:
    try:
        raw = await complete(prompt, max_tokens=10, temperature=0.0)
    except LlmUnavailableError:
        return fallback
    match = _SCORE_RE.search(raw)
    if not match:
        return fallback
    return max(0.0, min(1.0, float(match.group(0)) / 10))


async def score_faithfulness(answer: str, context: str) -> float:
    if is_abstention(answer):
        return 1.0  # correctly declining is maximally "faithful" — no unsupported claim made
    return await _score_0_to_10(_FAITHFULNESS_PROMPT.format(context=context, answer=answer))


async def score_relevancy(answer: str, question: str) -> float:
    return await _score_0_to_10(_RELEVANCY_PROMPT.format(question=question, answer=answer))


async def score_correctness(answer: str, ground_truth: str, question: str = "") -> float:
    return await _score_0_to_10(
        _CORRECTNESS_PROMPT.format(question=question, ground_truth=ground_truth, answer=answer)
    )


def is_abstention(answer: str) -> bool:
    lowered = answer.lower()
    return any(phrase in lowered for phrase in _ABSTENTION_PHRASES)


def citation_validity(answer: str, num_context_items: int) -> float:
    """Fraction of [n] markers in the answer that reference a real context item — a real,
    deterministic check (not LLM-judged): catches a model inventing citation numbers beyond
    what was actually retrieved."""
    markers = [int(m) for m in _CITATION_MARKER_RE.findall(answer)]
    if not markers:
        return 1.0  # no citations to be invalid — mandatory-citations is a separate concern
    valid = sum(1 for m in markers if 1 <= m <= num_context_items)
    return valid / len(markers)
