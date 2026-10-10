from __future__ import annotations

import pytest

from app.agents import verifier as verifier_module
from app.agents.verifier import _is_claim_grounded_in_answer, route_after_verifier, verifier_node


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
    assert _is_claim_grounded_in_answer(hallucinated_claim, answer) is False


def test_claim_grounded_accepts_a_claim_actually_quoted_from_the_answer() -> None:
    answer = "Employees get unlimited vacation and a free company car every year."
    assert _is_claim_grounded_in_answer("Employees get unlimited vacation.", answer) is True
    assert _is_claim_grounded_in_answer(answer, answer) is True


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

    monkeypatch.setattr(verifier_module, "complete", _fake_complete)

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
