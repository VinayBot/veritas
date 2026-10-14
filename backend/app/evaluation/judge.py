"""LLM-judge: scores generation quality on a 0-1 scale, or returns None when a score could
not be measured. Used both for the per-answer report
(reference-free -> labelled "Estimated") and the benchmark runner (against synthetic-dataset
ground truth -> labelled "Verified") — same scoring functions either way; the caller decides
the label based on whether a ground-truth answer was available, not this module.
"""

from __future__ import annotations

import re

from app.agents.citations import citation_markers
from app.llm.client import LlmUnavailableError, complete
from app.llm.models_config import get_model_config

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


def judge_model() -> str:
    return get_model_config().judge


async def _score_0_to_10(prompt: str) -> float | None:
    """None means "not measured": the judge model was unreachable or its reply contained no
    number. Callers must carry that through — a made-up midpoint would look like a result."""
    try:
        raw = await complete(prompt, model=judge_model(), max_tokens=10, temperature=0.0)
    except LlmUnavailableError:
        return None
    match = _SCORE_RE.search(raw)
    if not match:
        return None
    return max(0.0, min(1.0, float(match.group(0)) / 10))


async def score_faithfulness(answer: str, context: str) -> float | None:
    if is_abstention(answer):
        return 1.0  # correctly declining is maximally "faithful" — no unsupported claim made
    return await _score_0_to_10(_FAITHFULNESS_PROMPT.format(context=context, answer=answer))


async def score_relevancy(answer: str, question: str) -> float | None:
    return await _score_0_to_10(_RELEVANCY_PROMPT.format(question=question, answer=answer))


async def score_correctness(answer: str, ground_truth: str, question: str = "") -> float | None:
    return await _score_0_to_10(
        _CORRECTNESS_PROMPT.format(question=question, ground_truth=ground_truth, answer=answer)
    )


_COMBINED_PROMPT = (
    "You are grading an answer. Give each score as a whole number from 0 to 10.\n\n"
    "Question: {question}\n\nAnswer: {answer}\n{extras}\n"
    "Scores to give:\n{criteria}\n\n"
    "Reply with exactly one line per score in the form `name: number` and nothing else."
)
_CRITERIA = {
    "faithfulness": (
        "faithfulness — how well every claim in the answer is directly supported by the "
        "context (10 = every claim explicitly supported, 0 = none, or it contradicts it)"
    ),
    "relevancy": (
        "relevancy — how directly and completely the answer addresses the question, "
        "regardless of whether it is correct"
    ),
    "correctness": (
        "correctness — how consistent the answer's meaning is with the reference answer "
        "(same meaning, not necessarily the same wording)"
    ),
}


async def score_all(
    answer: str,
    question: str,
    *,
    context: str | None = None,
    ground_truth: str | None = None,
) -> dict[str, float | None]:
    """Faithfulness, relevancy and correctness from one judge call instead of three — the
    same rubric wording as the single-score functions, a third of the model time. A score is
    only asked for when what it needs is present (context for faithfulness, a reference for
    correctness); anything not asked for, or missing from the reply, is None."""
    wanted = ["relevancy"]
    extras = ""
    result: dict[str, float | None] = {"faithfulness": None, "relevancy": None, "correctness": None}
    if context and context.strip():
        if is_abstention(answer):
            result["faithfulness"] = 1.0  # declining makes no unsupported claim
        else:
            wanted.insert(0, "faithfulness")
            extras += f"\nContext:\n{context[:6000]}\n"
    if ground_truth and ground_truth.strip():
        if says_not_covered(answer) and not says_not_covered(ground_truth):
            # Reproduced in a live comparison: "Excerpt 1 does not mention the father of AI"
            # was scored 1.0 against a reference that names him. Saying the document lacks
            # what it has is wrong, whatever the judge model says.
            result["correctness"] = 0.0
        else:
            wanted.append("correctness")
            extras += f"\nReference answer: {ground_truth}\n"
    prompt = _COMBINED_PROMPT.format(
        question=question,
        answer=answer,
        extras=extras,
        criteria="\n".join(f"- {_CRITERIA[name]}" for name in wanted),
    )
    try:
        raw = await complete(prompt, model=judge_model(), max_tokens=40, temperature=0.0)
    except LlmUnavailableError:
        return result
    for name in wanted:
        match = re.search(rf"{name}\W*?(\d+(?:\.\d+)?)", raw, re.IGNORECASE)
        if match:
            result[name] = max(0.0, min(1.0, float(match.group(1)) / 10))
    return result


_NOT_COVERED_RE = re.compile(
    r"\b(?:does not|doesn't|do not|don't) (?:mention|contain|say|state|include|provide)\b"
    r"|\bnot (?:mentioned|answerable|stated|covered)\b|\bno information (?:about|on)\b",
    re.I,
)


def says_not_covered(text: str) -> bool:
    """An abstention, or a reply that the document does not hold the answer."""
    return is_abstention(text) or bool(_NOT_COVERED_RE.search(text))


def is_abstention(answer: str) -> bool:
    lowered = answer.lower()
    return any(phrase in lowered for phrase in _ABSTENTION_PHRASES)


def citation_validity(answer: str, num_context_items: int) -> float:
    """Fraction of [n] markers in the answer that reference a real context item — a real,
    deterministic check (not LLM-judged): catches a model inventing citation numbers beyond
    what was actually retrieved."""
    markers = citation_markers(answer)
    if not markers:
        return 1.0  # no citations to be invalid — mandatory-citations is a separate concern
    valid = sum(1 for m in markers if 1 <= m <= num_context_items)
    return valid / len(markers)
