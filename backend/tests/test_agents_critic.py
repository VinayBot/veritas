from __future__ import annotations

from app.agents.critic import critic_node, route_after_critic
from app.agents.state import MAX_CRITIC_LOOPS


async def test_critic_with_no_evidence_is_insufficient() -> None:
    state = {
        "session_id": "s1",
        "query": "What is the vacation policy?",
        "retrieved": [],
        "loop_count": 0,
    }
    result = await critic_node(state)
    assert result["critic_verdict"] == "insufficient"
    assert result["loop_count"] == 1


async def test_critic_with_strong_evidence_is_sufficient() -> None:
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
        "loop_count": 0,
    }
    result = await critic_node(state)
    assert result["critic_verdict"] == "sufficient"
    assert result["loop_count"] == 0  # not incremented when sufficient


def test_route_after_critic_retries_under_the_cap() -> None:
    state = {"critic_verdict": "insufficient", "loop_count": MAX_CRITIC_LOOPS - 1}
    assert route_after_critic(state) == "retry"


def test_route_after_critic_proceeds_at_the_cap() -> None:
    state = {"critic_verdict": "insufficient", "loop_count": MAX_CRITIC_LOOPS}
    assert route_after_critic(state) == "proceed"


def test_route_after_critic_proceeds_when_sufficient() -> None:
    state = {"critic_verdict": "sufficient", "loop_count": 0}
    assert route_after_critic(state) == "proceed"
