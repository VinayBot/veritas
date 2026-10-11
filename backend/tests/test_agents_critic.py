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


async def test_critic_with_one_strong_hit_among_weak_filler_is_sufficient() -> None:
    """Reproduces a live bug: cross-encoder rerank scores for genuinely irrelevant chunks run
    much more negative (observed -8 to -11) than a correct top hit runs positive (observed
    +4.6), so averaging the whole top-k let 3 irrelevant filler chunks veto 1 excellent one —
    the question was wrongly judged unanswerable despite the right chunk sitting at rank 1."""
    state = {
        "session_id": "s1",
        "query": "Can a German contractor work remotely without approval?",
        "retrieved": [
            {
                "chunk_id": "c1",
                "text": (
                    "Contractors who are not based in the country where the company maintains "
                    "a registered entity may not work remotely without a written exception "
                    "approved by the Head of Global Compliance. This includes contractors "
                    "based in Germany, who must obtain that written exception before working "
                    "remotely under this policy."
                ),
                "score": 4.6,
            },
            {
                "chunk_id": "c2",
                "text": (
                    "Employees are reimbursed for reasonable incidental expenses while "
                    "traveling, including a daily meal allowance that varies by destination."
                ),
                "score": -8.0,
            },
            {
                "chunk_id": "c3",
                "text": (
                    "Company laptops must remain encrypted and within the employee's physical "
                    "possession or a locked hotel safe at all times while traveling."
                ),
                "score": -8.2,
            },
            {
                "chunk_id": "c4",
                "text": (
                    "Employees may extend a business trip with personal vacation days, "
                    "commonly called a bleisure trip, provided the personal portion is "
                    "clearly marked in the booking."
                ),
                "score": -11.1,
            },
        ],
        "loop_count": 0,
    }
    result = await critic_node(state)
    assert result["critic_verdict"] == "sufficient"


def test_route_after_critic_retries_under_the_cap() -> None:
    state = {"critic_verdict": "insufficient", "loop_count": MAX_CRITIC_LOOPS - 1}
    assert route_after_critic(state) == "retry"


def test_route_after_critic_proceeds_at_the_cap() -> None:
    state = {"critic_verdict": "insufficient", "loop_count": MAX_CRITIC_LOOPS}
    assert route_after_critic(state) == "proceed"


def test_route_after_critic_proceeds_when_sufficient() -> None:
    state = {"critic_verdict": "sufficient", "loop_count": 0}
    assert route_after_critic(state) == "proceed"
