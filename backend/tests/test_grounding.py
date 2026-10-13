from __future__ import annotations

import pytest

from app.evaluation import grounding
from app.evaluation.grounding import ground_answer

CONTEXT = (
    "Employees accrue two paid vacation days per month of service, up to a maximum of "
    "twenty-four days per year. Managers must approve requests two weeks in advance."
)


async def test_supported_answer_is_fully_grounded() -> None:
    report = await ground_answer(
        "Employees accrue two paid vacation days per month of service [1]. "
        "The maximum is twenty-four days per year [1].",
        CONTEXT,
    )
    assert report is not None
    assert report.total == 2
    assert report.score == 1.0
    assert all(s["supported"] for s in report.sentences)


async def test_an_invented_sentence_is_marked_unsupported_and_lowers_the_score() -> None:
    report = await ground_answer(
        "Employees accrue two paid vacation days per month of service [1]. "
        "Every employee also receives a company car and unlimited sabbatical leave.",
        CONTEXT,
    )
    assert report is not None
    assert report.total == 2
    flagged = [s for s in report.sentences if not s["supported"]]
    assert len(flagged) == 1
    assert "company car" in flagged[0]["text"]
    assert report.score == 0.5
    assert report.supported == 1


async def test_abstentions_and_empty_context_are_not_scored() -> None:
    assert await ground_answer("I don't have enough information to answer that.", CONTEXT) is None
    assert await ground_answer("Employees accrue two days per month.", "") is None


async def test_unavailable_checker_means_not_measured(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm.client import LlmUnavailableError

    async def unavailable(*_args: object, **_kwargs: object) -> str:
        raise LlmUnavailableError("down")

    monkeypatch.setattr(grounding, "complete", unavailable)
    assert await ground_answer("Employees accrue two days per month of service.", CONTEXT) is None


async def test_a_finding_that_quotes_the_context_is_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The model slip this guards against: flagging a sentence that is verbatim in the context."""

    async def slip(*_args: object, **_kwargs: object) -> str:
        return '["Employees accrue two paid vacation days per month of service"]'

    monkeypatch.setattr(grounding, "complete", slip)
    report = await ground_answer(
        "Employees accrue two paid vacation days per month of service.", CONTEXT
    )
    assert report is not None and report.score == 1.0
