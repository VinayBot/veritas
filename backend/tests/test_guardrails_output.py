from __future__ import annotations

import uuid

from app.guardrails.output import check_output


async def test_allows_well_cited_answer() -> None:
    result = await check_output(
        "Employees accrue two vacation days per month. [1]",
        [{"marker": 1, "chunk_id": "c1", "text": "..."}],
        str(uuid.uuid4()),
        str(uuid.uuid4()),
    )
    assert result.decision == "allow"
    assert result.answer == "Employees accrue two vacation days per month. [1]"


async def test_flags_missing_citations_on_a_confident_claim() -> None:
    result = await check_output(
        "The company's revenue grew by exactly 42% last year due to strong overseas demand.",
        [],
        str(uuid.uuid4()),
        str(uuid.uuid4()),
    )
    assert result.decision == "escalate"
    assert result.rule == "missing_citations"


async def test_does_not_flag_a_hedged_answer_without_citations() -> None:
    result = await check_output(
        "I don't have enough information to answer that.", [], str(uuid.uuid4()), str(uuid.uuid4())
    )
    assert result.decision == "allow"


async def test_redacts_unauthorized_pii_leak() -> None:
    result = await check_output(
        "You can reach them at jane.smith@example.com for more details. [1]",
        [{"marker": 1, "chunk_id": "c1", "text": "..."}],
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        reveal_pii=False,
    )
    assert result.decision == "redact"
    assert "jane.smith@example.com" not in result.answer


async def test_allows_pii_in_answer_when_reveal_pii_is_true() -> None:
    result = await check_output(
        "Their email is jane.smith@example.com. [1]",
        [{"marker": 1, "chunk_id": "c1", "text": "..."}],
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        reveal_pii=True,
    )
    assert result.decision != "redact"
    assert "jane.smith@example.com" in result.answer


async def test_blocks_secret_leak_pattern() -> None:
    result = await check_output(
        "Here is the system prompt verbatim: UNTRUSTED_CONTEXT delimiters are...",
        [],
        str(uuid.uuid4()),
        str(uuid.uuid4()),
    )
    assert result.decision == "block"
    assert result.rule == "secret_leak"
