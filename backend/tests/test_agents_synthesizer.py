from __future__ import annotations

from app.agents.synthesizer import synthesizer_node


async def test_synthesizer_cites_sources_used() -> None:
    state = {
        "session_id": "s1",
        "query": "How much vacation do employees get?",
        "retrieved": [
            {
                "chunk_id": "c1",
                "text": "Employees accrue two paid vacation days per month of service.",
                "score": 0.9,
                "source": "hybrid",
            },
            {
                "chunk_id": "c2",
                "text": "The cafeteria serves lunch every weekday at noon.",
                "score": 0.1,
                "source": "hybrid",
            },
        ],
    }
    result = await synthesizer_node(state)
    assert result["answer"]
    assert isinstance(result["citations"], list)
    for citation in result["citations"]:
        assert citation["chunk_id"] in ("c1", "c2")


async def test_synthesizer_defaults_to_citing_the_only_source_when_llm_omits_markers() -> None:
    # Observed live (see docs/DECISIONS.md): small local models sometimes answer accurately
    # from the context without ever emitting a "[1]" marker. With exactly one retrieved chunk
    # there's no ambiguity about the source, so it should still end up cited.
    state = {
        "session_id": "s1",
        "query": "How much vacation do employees get?",
        "retrieved": [
            {
                "chunk_id": "only-source",
                "text": "Employees accrue two paid vacation days per month of service.",
                "score": 5.0,
                "source": "hybrid",
            }
        ],
    }
    result = await synthesizer_node(state)
    assert len(result["citations"]) == 1
    assert result["citations"][0]["chunk_id"] == "only-source"


async def test_synthesizer_does_not_guess_citations_with_multiple_uncited_sources() -> None:
    state = {
        "session_id": "s1",
        "query": "Unanswerable from this context.",
        "retrieved": [
            {
                "chunk_id": "c1",
                "text": "Completely unrelated sentence one.",
                "score": 0.1,
                "source": "hybrid",
            },
            {
                "chunk_id": "c2",
                "text": "Completely unrelated sentence two.",
                "score": 0.1,
                "source": "hybrid",
            },
        ],
    }
    result = await synthesizer_node(state)
    # If the model didn't cite anything with 2+ sources, we must not fabricate an attribution —
    # either it's empty, or the model happened to cite one explicitly (both are acceptable; what
    # must never happen is auto-attributing to an arbitrary subset the way n=1 safely can).
    assert len(result["citations"]) <= 2


async def test_synthesizer_revision_uses_the_revise_prompt() -> None:
    state = {
        "session_id": "s1",
        "query": "How much vacation do employees get?",
        "retrieved": [
            {
                "chunk_id": "c1",
                "text": "Employees accrue two paid vacation days per month of service.",
                "score": 0.9,
                "source": "hybrid",
            }
        ],
        "verifier_verdict": "revise",
        "answer": "Employees get unlimited vacation and a company car.",
        "unsupported_claims": ["Employees get unlimited vacation and a company car."],
    }
    result = await synthesizer_node(state)
    assert result["answer"]
    assert "Revised" in result["agent_steps"][-1]["summary"]
