"""Assembles the agentic RAG state machine.

Linear path: guardian_in -> planner -> rewriter -> retriever -> critic -> synthesizer
             -> verifier -> guardian_out -> END

Two loops back:
- critic, when evidence is insufficient and under the retry cap, loops back to rewriter
  (which tries a different rewrite technique each time — see rewriter.py).
- verifier, when it finds unsupported claims and under the revision cap, loops back to
  synthesizer for one corrected attempt.

Two early exits, both straight to guardian_out (no point running the rest of the pipeline):
- guardian_in blocks the input (rate limit / encoding / injection / unsafe content).
- the Planner classifies the query as out_of_scope.
"""

from __future__ import annotations

from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.agents.critic import critic_node, route_after_critic
from app.agents.guardian import guardian_in_node, guardian_out_node, route_after_guardian_in
from app.agents.planner import decline_node, planner_node, route_after_planner
from app.agents.retriever import retriever_node
from app.agents.rewriter import rewriter_node
from app.agents.state import AgentState
from app.agents.synthesizer import synthesizer_node
from app.agents.verifier import route_after_verifier, verifier_node


def build_agent_graph():
    graph = StateGraph(AgentState)
    graph.add_node("guardian_in", guardian_in_node)
    graph.add_node("planner", planner_node)
    graph.add_node("decline", decline_node)
    graph.add_node("rewriter", rewriter_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("critic", critic_node)
    graph.add_node("synthesizer", synthesizer_node)
    graph.add_node("verifier", verifier_node)
    graph.add_node("guardian_out", guardian_out_node)

    graph.add_edge(START, "guardian_in")
    graph.add_conditional_edges(
        "guardian_in", route_after_guardian_in, {"blocked": "guardian_out", "continue": "planner"}
    )
    graph.add_conditional_edges(
        "planner", route_after_planner, {"out_of_scope": "decline", "continue": "rewriter"}
    )
    graph.add_edge("decline", "guardian_out")
    graph.add_edge("rewriter", "retriever")
    graph.add_edge("retriever", "critic")
    graph.add_conditional_edges(
        "critic", route_after_critic, {"retry": "rewriter", "proceed": "synthesizer"}
    )
    graph.add_edge("synthesizer", "verifier")
    graph.add_conditional_edges(
        "verifier", route_after_verifier, {"revise": "synthesizer", "proceed": "guardian_out"}
    )
    graph.add_edge("guardian_out", END)

    return graph.compile()


@lru_cache(maxsize=1)
def get_agent_graph():
    return build_agent_graph()
