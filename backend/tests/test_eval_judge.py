from __future__ import annotations

import pytest

from app.evaluation.judge import (
    citation_validity,
    is_abstention,
    score_correctness,
    score_faithfulness,
    score_relevancy,
)


def test_is_abstention_detects_hedge_phrases() -> None:
    assert is_abstention("I don't have enough information to answer that.")
    assert not is_abstention("Employees accrue two vacation days per month.")


def test_citation_validity_all_valid() -> None:
    assert (
        citation_validity("Employees get two days. [1] Approved in [2].", num_context_items=2)
        == 1.0
    )


def test_citation_validity_catches_invented_citation() -> None:
    score = citation_validity("See [1] and the invented [7].", num_context_items=2)
    assert score == 0.5


def test_citation_validity_no_citations_is_vacuously_valid() -> None:
    assert citation_validity("No citations here.", num_context_items=3) == 1.0


async def test_faithfulness_scores_abstention_as_fully_faithful() -> None:
    score = await score_faithfulness(
        "I don't have enough information to answer that.", "irrelevant context"
    )
    assert score == 1.0


async def test_faithfulness_scores_well_supported_answer_highly() -> None:
    score = await score_faithfulness(
        "Employees accrue two vacation days per month.",
        "Employees accrue two paid vacation days per month of service.",
    )
    assert score >= 0.7


async def test_faithfulness_scores_contradicted_answer_low() -> None:
    score = await score_faithfulness(
        "Employees get unlimited vacation and a free car every year.",
        "Employees accrue two paid vacation days per month of service.",
    )
    assert score <= 0.4


async def test_relevancy_scores_on_topic_answer_highly() -> None:
    score = await score_relevancy(
        "Employees accrue two vacation days per month.", "How much vacation do employees get?"
    )
    assert score >= 0.6


async def test_correctness_matches_semantically_equivalent_phrasing() -> None:
    score = await score_correctness(
        "Workers earn 2 days of PTO monthly.",
        ground_truth="Employees accrue two vacation days per month.",
        question="How much vacation do employees get?",
    )
    assert score >= 0.6


async def test_an_unreachable_judge_yields_not_measured_never_a_made_up_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.evaluation import judge
    from app.llm.client import LlmUnavailableError

    async def unavailable(*_args: object, **_kwargs: object) -> str:
        raise LlmUnavailableError("judge down")

    monkeypatch.setattr(judge, "complete", unavailable)
    assert await score_relevancy("An answer.", "A question?") is None
    assert await score_correctness("An answer.", "Truth.", "A question?") is None
    assert await score_faithfulness("An answer.", "Some context.") is None


async def test_a_judge_reply_with_no_number_is_not_measured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.evaluation import judge

    async def waffle(*_args: object, **_kwargs: object) -> str:
        return "I think this answer is quite good overall."

    monkeypatch.setattr(judge, "complete", waffle)
    assert await score_relevancy("An answer.", "A question?") is None
