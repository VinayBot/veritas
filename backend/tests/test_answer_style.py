from __future__ import annotations

import pytest

from app.agents.answer_style import resolve_detail, style_for, wants_depth


@pytest.mark.parametrize(
    "question",
    [
        "How many vacation days do employees get?",
        "Who approves remote work?",
        "What is the travel limit",
        "Is a deposit required?",  # "deposit" must not read as "deep"
    ],
)
def test_a_normal_question_gets_a_quick_answer(question: str) -> None:
    assert not wants_depth(question)
    assert resolve_detail(question) == "brief"


@pytest.mark.parametrize(
    "question",
    [
        "Explain the vacation policy in detail",
        "Give me a deep dive on remote work eligibility",
        "Can you elaborate on the approval process?",
        "I need a detailed answer about travel expenses",
        "Walk me through the reimbursement steps",
        "give a comprehensive explanation of the probation rules",
        "explain in-depth how accrual works",
    ],
)
def test_asking_for_depth_gets_the_deep_answer(question: str) -> None:
    assert wants_depth(question)
    assert resolve_detail(question) == "deep"


def test_an_explicit_choice_overrides_the_phrasing() -> None:
    assert resolve_detail("Explain in detail", "brief") == "brief"
    assert resolve_detail("Quick question", "deep") == "deep"
    assert resolve_detail("Quick question", "auto") == "brief"  # anything else = decide


def test_styles_ask_for_the_promised_lengths() -> None:
    brief, deep = style_for("brief"), style_for("deep")
    assert "3 to 4 lines" in brief.instruction
    assert "7 to 8 lines" in deep.instruction
    assert brief.max_tokens < deep.max_tokens
    assert brief.prefer_fast_model and not deep.prefer_fast_model
    assert style_for(None) == brief


def test_tidy_answer_drops_a_trailing_reference_list_only() -> None:
    from app.agents.answer_style import tidy_answer

    body = "Flights must be booked 14 days ahead [1]. Upgrades need approval [2]."
    assert tidy_answer(body + "\n\nReferences:\n\n[1] Policy\n[2] Travel") == body
    assert tidy_answer(body) == body
    assert tidy_answer("See the references section of the policy [1].") == (
        "See the references section of the policy [1]."
    )


def test_tidy_answer_enforces_the_requested_length_by_dropping_trailing_sentences() -> None:
    from app.agents.answer_style import tidy_answer

    ten = " ".join(f"Rule {i} applies to trips over 5.5 days [{i}]." for i in range(1, 11))
    assert tidy_answer(ten, "brief").count("applies") == 4
    assert tidy_answer(ten, "deep").count("applies") == 8
    assert tidy_answer(ten, "deep").endswith("[8].")
    assert tidy_answer(ten) == ten  # no length asked for, nothing removed

    cut_off = (
        "Flights go through the portal [1]. Upgrades need a manager [2]. "
        "The threshold was raised from eight"
    )
    assert (
        tidy_answer(cut_off, "deep")
        == "Flights go through the portal [1]. Upgrades need a manager [2]."
    )
    short = "The stipend is six hundred dollars [1]."
    assert tidy_answer(short, "brief") == short
