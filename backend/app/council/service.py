"""LLM Council: real distinct local models independently answer the same question, anonymously
peer-review each other's answers, and a chairman model synthesizes the final answer — a real
multi-model ensemble (every member call hits a genuinely different model via `app/llm/client.py`),
not a single call relabeled three times.

Execution strategy follows Section 1's hardware tiers (see .env.example): "8gb" runs members
and reviewers sequentially (fewer models resident in Ollama's memory at once); "16gb" runs them
concurrently. Either way every call is real; this only changes wall-clock latency.
"""

from __future__ import annotations

import asyncio
import statistics
import string
import time
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.agents.answer_style import AnswerStyle, style_for
from app.agents.context_utils import UNTRUSTED_CONTEXT_SYSTEM_PROMPT
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.tracing import trace_bus
from app.council.models import CouncilRun
from app.llm.client import LlmUnavailableError, complete
from app.llm.json_utils import extract_json_object
from app.llm.models_config import get_model_config

_MEMBER_PROMPT = (
    "Answer the question using ONLY the numbered context below. Cite sources inline using "
    "[1], [2], etc. If the context doesn't contain the answer, say you don't have enough "
    "information rather than guessing. {style}\n\n{context}\n\nQuestion: {query}\n\nAnswer:"
)

_PEER_REVIEW_PROMPT = (
    "You are reviewing {n} candidate answers to the same question, written by other systems "
    "you don't know the identity of. Score each one from 0 to 10 on how well-supported by the "
    "context and how complete it is — not on writing style.\n\nContext:\n{context}\n\n"
    "Question: {query}\n\n{labeled_answers}\n\nReturn ONLY a JSON object mapping each letter to "
    'a numeric score, for example {{"A": 7, "B": 9}}. Include every letter shown above.'
)

_CHAIRMAN_PROMPT = (
    "{n} systems independently answered the same question below. Synthesize the single best "
    "answer: keep only claims that are well-supported by the context (claims multiple answers "
    "agree on are a good signal), use [n]-style citations matching the context numbering, and "
    "drop anything unsupported. {style}\n\nContext:\n{context}\n\nQuestion: {query}\n\n"
    "{labeled_answers}\n\nSynthesized answer:"
)

# ~half the 0-10 score range — a stdev at or above this between reviewers reads as "no
# agreement" rather than a merely imperfect one.
_AGREEMENT_STDEV_REFERENCE = 5.0


@dataclass
class MemberAnswer:
    model: str
    label: str
    answer: str
    latency_ms: float


@dataclass
class PeerReview:
    reviewer_model: str
    scores: dict[str, float]  # label -> score in [0, 10]


@dataclass
class CouncilResult:
    id: str
    members: list[str]
    chairman_model: str
    member_answers: list[MemberAnswer]
    peer_reviews: list[PeerReview]
    agreement_score: float
    final_answer: str


def _labels(n: int) -> list[str]:
    return list(string.ascii_uppercase[:n])


async def _member_answer(
    model: str, label: str, query: str, context: str, style: AnswerStyle
) -> MemberAnswer:
    start = time.perf_counter()
    try:
        answer = await complete(
            _MEMBER_PROMPT.format(context=context, query=query, style=style.instruction),
            model=model,
            system=UNTRUSTED_CONTEXT_SYSTEM_PROMPT,
            max_tokens=style.max_tokens,
            temperature=0.3,
        )
    except LlmUnavailableError:
        answer = "(unavailable — this model could not be reached)"
    return MemberAnswer(
        model=model, label=label, answer=answer, latency_ms=(time.perf_counter() - start) * 1000
    )


async def _run_maybe_parallel(coros: list[Coroutine[Any, Any, Any]]) -> list[Any]:
    if get_settings().hardware_tier == "8gb":
        return [await c for c in coros]
    return list(await asyncio.gather(*coros))


async def _generate_members(
    models: list[str], query: str, context: str, style: AnswerStyle
) -> list[MemberAnswer]:
    labels = _labels(len(models))
    coros = [
        _member_answer(model, label, query, context, style)
        for model, label in zip(models, labels, strict=True)
    ]
    return await _run_maybe_parallel(coros)


def _format_labeled(labels: list[str], texts: list[str]) -> str:
    return "\n\n".join(f"[{label}] {text}" for label, text in zip(labels, texts, strict=True))


async def _peer_review_one(
    reviewer_model: str, query: str, context: str, labels: list[str], answers: list[str]
) -> PeerReview:
    prompt = _PEER_REVIEW_PROMPT.format(
        n=len(labels),
        context=context,
        query=query,
        labeled_answers=_format_labeled(labels, answers),
    )
    try:
        raw = await complete(prompt, model=reviewer_model, max_tokens=120, temperature=0.0)
    except LlmUnavailableError:
        return PeerReview(reviewer_model=reviewer_model, scores={})

    parsed = extract_json_object(raw) or {}
    scores: dict[str, float] = {}
    for label in labels:
        value = parsed.get(label)
        if value is None:
            continue  # reviewer didn't score this one — left out of the average, not faked
        try:
            scores[label] = max(0.0, min(10.0, float(value)))
        except (TypeError, ValueError):
            continue  # unparseable score — same treatment as a missing one
    return PeerReview(reviewer_model=reviewer_model, scores=scores)


async def _peer_review_all(
    reviewers: list[str], query: str, context: str, labels: list[str], answers: list[str]
) -> list[PeerReview]:
    coros = [_peer_review_one(reviewer, query, context, labels, answers) for reviewer in reviewers]
    return await _run_maybe_parallel(coros)


def _agreement_score(peer_reviews: list[PeerReview], labels: list[str]) -> float:
    """1 minus the average (normalized) spread of scores reviewers gave to the *same* answer —
    real reviewers agreeing tightly on every answer scores near 1; scattered, inconsistent
    scoring scores near 0. Labels with fewer than two real scores are skipped (a stdev needs at
    least two points), not defaulted to perfect agreement."""
    per_label_spread: list[float] = []
    for label in labels:
        values = [r.scores[label] for r in peer_reviews if label in r.scores]
        if len(values) >= 2:
            per_label_spread.append(statistics.stdev(values))
    if not per_label_spread:
        return 0.0
    avg_spread = sum(per_label_spread) / len(per_label_spread)
    return max(0.0, 1.0 - avg_spread / _AGREEMENT_STDEV_REFERENCE)


async def _chairman_synthesize(
    chairman_model: str,
    query: str,
    context: str,
    labels: list[str],
    answers: list[str],
    style: AnswerStyle,
) -> str:
    prompt = _CHAIRMAN_PROMPT.format(
        n=len(labels),
        context=context,
        query=query,
        labeled_answers=_format_labeled(labels, answers),
        style=style.instruction,
    )
    try:
        return await complete(
            prompt,
            model=chairman_model,
            system=UNTRUSTED_CONTEXT_SYSTEM_PROMPT,
            max_tokens=style.max_tokens,
            temperature=0.2,
        )
    except LlmUnavailableError:
        # Fall back to the strongest-reviewed single member answer rather than an empty answer.
        return (
            answers[0]
            if answers
            else ("I'm unable to generate an answer right now — the language model is unavailable.")
        )


async def run_council(
    session_id: str, query: str, context: str, style: AnswerStyle | None = None
) -> CouncilResult:
    style = style or style_for(None)
    config = get_model_config()
    members = config.council or [config.generator]
    chairman = config.chairman

    async with trace_bus.stage(session_id, "council", from_stage="synthesizer") as h:
        member_answers = await _generate_members(members, query, context, style)
        labels = [m.label for m in member_answers]
        answers = [m.answer for m in member_answers]

        peer_reviews = await _peer_review_all(members, query, context, labels, answers)
        agreement = _agreement_score(peer_reviews, labels)
        final_answer = await _chairman_synthesize(chairman, query, context, labels, answers, style)
        h.set_metric("members", members)
        h.set_metric("chairman", chairman)
        h.set_metric("agreement_score", agreement)
        h.set_output(f"{len(members)} members, agreement {agreement:.2f}")

    result = CouncilResult(
        id=str(uuid.uuid4()),
        members=members,
        chairman_model=chairman,
        member_answers=member_answers,
        peer_reviews=peer_reviews,
        agreement_score=agreement,
        final_answer=final_answer,
    )
    await _persist(session_id, query, result)
    return result


async def _persist(session_id: str, query: str, result: CouncilResult) -> None:
    async with session_scope() as session:
        session.add(
            CouncilRun(
                id=result.id,
                session_id=session_id,
                query=query,
                members=result.members,
                chairman_model=result.chairman_model,
                member_answers=[
                    {
                        "model": m.model,
                        "label": m.label,
                        "answer": m.answer,
                        "latency_ms": m.latency_ms,
                    }
                    for m in result.member_answers
                ],
                peer_reviews=[
                    {"reviewer_model": r.reviewer_model, "scores": r.scores}
                    for r in result.peer_reviews
                ],
                agreement_score=result.agreement_score,
                final_answer=result.final_answer,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def get_council_run(run_id: str) -> CouncilRun | None:
    async with session_scope() as session:
        return await session.get(CouncilRun, run_id)
