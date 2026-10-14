from __future__ import annotations

import pytest

from app.agents.answer_style import resolve_detail, style_for, tidy_answer, wants_depth


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


def test_a_sentence_ending_in_a_number_still_counts_as_a_sentence() -> None:
    """Reported: a quick answer ran to six sentences because "...ALICE in 1995. These..."
    was not counted as a sentence end."""
    from app.agents.answer_style import tidy_answer

    text = (
        "ELIZA appeared in 1966. PARRY followed in 1972. ALICE arrived in 1995. "
        "Siri launched in 2011. Alexa came in 2014. Bots now use deep learning."
    )
    assert tidy_answer(text, "brief") == (
        "ELIZA appeared in 1966. PARRY followed in 1972. ALICE arrived in 1995. "
        "Siri launched in 2011."
    )
    assert tidy_answer("Trips over 5.5 days need approval [1]. Book early.", "brief") == (
        "Trips over 5.5 days need approval [1]. Book early."
    )


def test_a_numbered_list_becomes_prose_and_is_held_to_length() -> None:
    from app.agents.answer_style import tidy_answer

    text = (
        "1. Chatbots began in 1966 with ELIZA. It matched keywords.\n\n"
        "2. PARRY came in 1972. ALICE followed in 1995.\n\n"
        "3. Modern bots use neural networks."
    )
    out = tidy_answer(text, "brief")
    assert "\n" not in out and not out.startswith("1.")
    assert out == (
        "Chatbots began in 1966 with ELIZA. It matched keywords. "
        "PARRY came in 1972. ALICE followed in 1995."
    )


def test_headings_and_meta_sentences_are_dropped():
    answer = (
        "The provided text appears to be a collection of passages about chatbots. Here's a "
        "summary of the main points:\n\n**Types of Chatbots**\n\n"
        "1. Dialog Flow: a Google platform [3]\n2. Meya.ai: offers a live debugger [2]\n"
    )
    assert tidy_answer(answer, "brief") == (
        "Dialog Flow: a Google platform [3]. Meya.ai: offers a live debugger [2]."
    )


def test_a_meta_sentence_alone_is_kept():
    answer = "The provided text does not say when chatbots began."
    assert tidy_answer(answer, "brief") == answer
