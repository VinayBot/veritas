from __future__ import annotations

import pytest

from app.agents.verifier import route_after_verifier, verifier_node
from app.evaluation import grounding as grounding_module
from app.evaluation.grounding import is_claim_in_answer, is_claim_in_context


async def test_verifier_accepts_a_well_supported_answer() -> None:
    state = {
        "session_id": "s1",
        "retrieved": [
            {
                "chunk_id": "c1",
                "text": "Employees accrue two paid vacation days per month of service.",
                "score": 0.9,
                "source": "hybrid",
            }
        ],
        "answer": "Employees accrue two paid vacation days per month of service. [1]",
        "revise_count": 0,
    }
    result = await verifier_node(state)
    assert result["verifier_verdict"] in (
        "supported",
        "revise",
    )  # LLM-dependent, but never abstain here
    assert "unsupported_claims" in result


@pytest.mark.needs_ollama
async def test_verifier_flags_unsupported_claim_and_requests_revision() -> None:
    state = {
        "session_id": "s1",
        "retrieved": [
            {
                "chunk_id": "c1",
                "text": "Employees accrue two paid vacation days per month of service.",
                "score": 0.9,
                "source": "hybrid",
            }
        ],
        "answer": "Employees get unlimited vacation and a free company car every year.",
        "revise_count": 0,
    }
    result = await verifier_node(state)
    assert result["verifier_verdict"] in ("revise", "abstain")
    if result["verifier_verdict"] == "revise":
        assert result["revise_count"] == 1


async def test_verifier_abstains_after_revise_cap_reached() -> None:
    state = {
        "session_id": "s1",
        "retrieved": [
            {
                "chunk_id": "c1",
                "text": "Unrelated content about lunch menus.",
                "score": 0.9,
                "source": "hybrid",
            }
        ],
        "answer": "The company stock price doubled last quarter.",
        "revise_count": 1,  # already at MAX_REVISE_LOOPS
    }
    result = await verifier_node(state)
    if result["unsupported_claims"]:
        assert result["verifier_verdict"] == "abstain"
        assert "enough" in result["answer"].lower()
        assert result["citations"] == []


async def test_verifier_accepts_a_multi_clause_sentence_copied_almost_verbatim() -> None:
    """Reproduced live against the real demo fixture (see docs/TROUBLESHOOTING.md): even the
    stronger council model occasionally flagged this exact sentence as unsupported once the
    surrounding chunk was its real, full ~2600-char length (several unrelated sections sharing
    the chunk) rather than a short, isolated excerpt — a shorter version of this same context
    did NOT reproduce it, which is why the full chunk is reproduced verbatim here rather than
    trimmed to just the relevant paragraph. The deterministic context-grounding check is what
    actually makes this reliable: it accepts the claim because the exact words are in the
    context, independent of what either model concludes. Strict on verdict, not just "never
    abstain", since this specific case was directly confirmed fixed, not just plausible either
    way."""
    context_text = (
        "## Northwind Collective - Remote Work &amp; Travel Policy\n\n"
        "Effective 2026. Policy owner: <PERSON_1eca5a>, People Operations Lead "
        "(priya.sharma@northwind-tech.example, <PHONE_NUMBER_9adbff>).\n\n"
        "## Remote Work Eligibility\n\n"
        "Employees who have completed a 90-day probationary period may work remotely for up "
        "to three days per week, subject to manager approval and the operational needs of "
        "their specific team. Employees still within their 90-day probationary period are "
        "expected to work on-site full time unless a documented medical or legal "
        "accommodation applies.\n\n"
        "## Equipment and Home Office Setup\n\n"
        "Equipment requests, including monitors, keyboards, and docking stations, are "
        "submitted through the IT helpdesk portal and typically ship within five business "
        "days. Remote employees are expected to be reachable during their team's core "
        "collaboration hours, defined as 10:00 to 15:00 in the employee's local time zone. "
        "Home office stipends of six hundred dollars annually are available to any employee "
        "who works remotely at least one day per week on a regular basis.\n\n"
        "## International Contractors\n\n"
        "Contractors who are not based in the country where Northwind Collective maintains a "
        "registered entity may not work remotely without a written exception approved by "
        "<PERSON_6cc6eb>, Head of Global Compliance. This includes contractors based in "
        "Germany, who must obtain <PERSON_6cc6eb>'s written exception before working remotely "
        "under this policy, regardless of the terms in their local contracting agreement.\n\n"
        "## Business Travel Approval Thresholds\n\n"
        "Business travel under one thousand dollars requires only the employee's direct "
        "manager's approval. Business travel between one thousand and four thousand nine "
        "hundred ninety-nine dollars requires approval from the relevant Vice President. "
        "Business travel of five thousand dollars or more requires approval from both the "
        "Vice President of Finance and the Chief Financial Officer, and must be requested at "
        "least fourteen business days before departure.\n\n"
        "## Restricted Travel Destinations\n\n"
        "Business travel to any location on the company's restricted-travel list requires "
        "pre-approval from both the employee's manager and the security team, regardless of "
        "trip duration or cost. Employees traveling internationally are automatically "
        "enrolled in a travel-tracking service that can locate and assist them in the event "
        "of a natural disaster, civil unrest, or medical emergency. All business travel must "
        "be booked through the approved travel portal so that the company can maintain "
        "accurate records of employee location for safety purposes.\n\n"
        "## Expenses While Traveling"
    )
    state = {
        "session_id": "s1",
        "retrieved": [{"chunk_id": "c1", "text": context_text, "score": 4.6, "source": "hybrid"}],
        "answer": (
            "According to the policy, contractors who are not based in the country where "
            "Northwind Collective maintains a registered entity may not work remotely without "
            "a written exception approved by <PERSON_6cc6eb>, Head of Global Compliance. This "
            "includes contractors based in Germany, who must obtain <PERSON_6cc6eb>'s written "
            "exception before working remotely under this policy, regardless of the terms in "
            "their local contracting agreement. [1]"
        ),
        "revise_count": 0,
    }
    result = await verifier_node(state)
    assert result["verifier_verdict"] == "supported"
    assert result["unsupported_claims"] == []


def test_claim_grounded_in_context_accepts_an_exact_quote() -> None:
    context = "Contractors based in Germany must obtain written exception before working remotely."
    claim = "Contractors based in Germany must obtain written exception before working remotely."
    assert is_claim_in_context(claim, context)


def test_claim_grounded_in_context_rejects_an_unrelated_claim() -> None:
    context = "Contractors based in Germany must obtain written exception before working remotely."
    claim = "The company offers unlimited vacation and a free car to every employee."
    assert not is_claim_in_context(claim, context)


def test_route_after_verifier() -> None:
    assert route_after_verifier({"verifier_verdict": "revise"}) == "revise"
    assert route_after_verifier({"verifier_verdict": "supported"}) == "proceed"
    assert route_after_verifier({"verifier_verdict": "abstain"}) == "proceed"


def test_claim_grounded_rejects_a_sentence_copied_from_context_not_the_answer() -> None:
    """Regression test for a real, reproduced failure (see docs/TROUBLESHOOTING.md's Bug B):
    asked to flag unsupported sentences IN THE ANSWER, the local 3B verifier model instead
    returned a sentence copied verbatim from the CONTEXT — valid JSON, not a real finding,
    since a context sentence trivially doesn't need to be "supported by the context"."""
    answer = "Employees can work remotely for up to three days per week, subject to approval."
    hallucinated_claim = (
        "Home office stipends of a fixed annual amount are available to any employee who "
        "works remotely at least one day per week on a regular basis."
    )
    assert is_claim_in_answer(hallucinated_claim, answer) is False


def test_claim_grounded_accepts_a_claim_actually_quoted_from_the_answer() -> None:
    answer = "Employees get unlimited vacation and a free company car every year."
    assert is_claim_in_answer("Employees get unlimited vacation.", answer) is True
    assert is_claim_in_answer(answer, answer) is True


async def test_verifier_discards_an_unsupported_claim_not_present_in_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end reproduction of the exact bug: the model's raw output is syntactically a
    valid JSON array, but names a sentence that never appears in `answer` — the fix must
    discard it and verify the answer as supported, instead of looping into an abstain."""

    async def _fake_complete(*_args: object, **_kwargs: object) -> str:
        return (
            '["Home office stipends of a fixed annual amount are available to any employee '
            'who works remotely at least one day per week on a regular basis."]'
        )

    monkeypatch.setattr(grounding_module, "complete", _fake_complete)

    state = {
        "session_id": "s1",
        "retrieved": [
            {
                "chunk_id": "c1",
                "text": (
                    "Employees may work remotely for up to three days per week, subject to "
                    "manager approval. Home office stipends of a fixed annual amount are "
                    "available to any employee who works remotely at least one day per week "
                    "on a regular basis."
                ),
                "score": 0.9,
                "source": "hybrid",
            }
        ],
        "answer": (
            "Employees may work remotely for up to three days per week, subject to manager "
            "approval. [1]"
        ),
        "revise_count": 0,
    }
    result = await verifier_node(state)
    assert result["verifier_verdict"] == "supported"
    assert result["unsupported_claims"] == []


def test_after_revision_unsupported_sentences_are_removed_not_the_whole_answer() -> None:
    """Reported: the agent declined a broad question because two of its sentences could not
    be supported. It now keeps the supported rest."""
    from app.agents.verifier import supported_part

    answer = (
        "ELIZA was created in 1966 [1]. PARRY followed in 1972 [2]. "
        "Chatbots were the first search engines. ALICE appeared in 1995 [3]."
    )
    kept = supported_part(answer, ["Chatbots were the first search engines."])
    assert (
        kept
        == "ELIZA was created in 1966 [1]. PARRY followed in 1972 [2]. ALICE appeared in 1995 [3]."
    )


def test_the_agent_still_declines_when_most_of_the_answer_is_unsupported() -> None:
    from app.agents.verifier import supported_part

    answer = "Bots began on Mars. They run on steam. ELIZA dates from 1966 [1]."
    assert supported_part(answer, ["Bots began on Mars.", "They run on steam."]) is None
    # A flagged claim that matches no sentence: unknown which part is wrong, so no trimming.
    assert supported_part(answer, ["Something the answer never said at all."]) is None
