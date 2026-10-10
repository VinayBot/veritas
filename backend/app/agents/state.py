"""The LangGraph state machine's shared state. Every node reads/returns a partial dict of this
shape — see app/agents/graph.py for how the nodes are wired together.
"""

from __future__ import annotations

from typing import Any, TypedDict

MAX_CRITIC_LOOPS = 3
MAX_REVISE_LOOPS = 1


class RetrievedChunk(TypedDict):
    chunk_id: str
    text: str
    score: float
    source: str  # "hybrid" | "graph"


class Citation(TypedDict):
    marker: int
    chunk_id: str
    text: str


class AgentState(TypedDict, total=False):
    session_id: str
    document_id: str | None
    query: str
    reveal_pii: bool
    council: bool
    council_run_id: str | None
    routing: dict[str, Any] | None

    category: str
    sub_questions: list[str]
    tools: list[str]

    search_text: str
    retrieved: list[RetrievedChunk]

    critic_score: float
    critic_verdict: str
    loop_count: int

    answer: str
    citations: list[Citation]

    verifier_verdict: str
    unsupported_claims: list[str]
    revise_count: int

    guardrail_status: str
    guardrail_reason: str

    agent_steps: list[dict[str, Any]]


def initial_state(
    query: str,
    session_id: str,
    document_id: str | None,
    reveal_pii: bool = False,
    council: bool = False,
) -> AgentState:
    return AgentState(
        session_id=session_id,
        document_id=document_id,
        query=query,
        reveal_pii=reveal_pii,
        council=council,
        council_run_id=None,
        routing=None,
        sub_questions=[],
        tools=[],
        retrieved=[],
        loop_count=0,
        revise_count=0,
        citations=[],
        agent_steps=[],
        guardrail_status="pending",
    )


def record_step(state: AgentState, node: str, summary: str) -> list[dict[str, Any]]:
    steps = list(state.get("agent_steps", []))
    steps.append({"node": node, "summary": summary})
    return steps
