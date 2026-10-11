"""Planner/Router: classifies the query, decomposes multi-part questions into sub-questions,
and picks which retrieval tools the Retriever node should use.
"""

from __future__ import annotations

import logging

from app.agents.state import AgentState, record_step
from app.core.tracing import trace_bus
from app.llm.client import LlmUnavailableError, complete
from app.llm.json_utils import extract_json_object

logger = logging.getLogger(__name__)

CATEGORIES = ("factoid", "multi_hop", "comparison", "summary", "pii_lookup", "out_of_scope")
ALL_TOOLS = ("hybrid_search", "graph_traverse", "pii_vault_lookup", "metadata_filter")

_PLANNER_PROMPT = """Classify this question and decide how to answer it. Return ONLY a JSON \
object, no other text, no markdown fences, with exactly these keys:
- "category": one of {categories}. Use "summary" for any broad question that asks for an \
overview, history, or general account spanning the whole document (e.g. "history of X", \
"tell me about X", "what is X") rather than one specific fact — these need wide, diverse \
retrieval across the document, not a single targeted lookup, and route differently.
- "sub_questions": a JSON array of 1-4 short, self-contained sub-questions. For a simple \
question, this is just the question itself as the only element. For a multi-hop or comparison \
question, break it into the separate facts that need to be looked up. For "summary", this is \
also just the question itself — breaking a broad question into narrow sub-questions defeats \
the point of asking for wide coverage.
- "tools": a JSON array chosen from {tools} — always include "hybrid_search" unless the \
question is purely about contact-lookup PII (then use "pii_vault_lookup"); add "graph_traverse" \
if answering requires connecting multiple entities/relationships.

Question: {query}

JSON object:"""


def _heuristic_fallback(query: str) -> dict:
    lowered = query.lower()
    category = "factoid"
    if any(w in lowered for w in ("compare", "versus", " vs ", "difference between")):
        category = "comparison"
    elif any(
        w in lowered
        for w in (
            "summarize",
            "summary",
            "overview",
            "history of",
            "tell me about",
            "what is the history",
            "background on",
        )
    ):
        category = "summary"
    elif any(w in lowered for w in ("email of", "phone number of", "who owns", "contact for")):
        category = "pii_lookup"
    tools = ["pii_vault_lookup"] if category == "pii_lookup" else ["hybrid_search"]
    return {"category": category, "sub_questions": [query], "tools": tools}


async def plan(query: str, model: str | None = None) -> dict:
    prompt = _PLANNER_PROMPT.format(categories=list(CATEGORIES), tools=list(ALL_TOOLS), query=query)
    try:
        raw = await complete(prompt, model=model, max_tokens=400, temperature=0.0)
    except LlmUnavailableError:
        logger.info("Planner: LLM unavailable, using heuristic classification")
        return _heuristic_fallback(query)

    parsed = extract_json_object(raw)
    if not parsed:
        return _heuristic_fallback(query)

    category = parsed.get("category") if parsed.get("category") in CATEGORIES else "factoid"
    sub_questions = parsed.get("sub_questions")
    if not isinstance(sub_questions, list) or not sub_questions:
        sub_questions = [query]
    sub_questions = [str(q) for q in sub_questions][:4]

    tools = parsed.get("tools")
    if not isinstance(tools, list) or not tools:
        tools = ["hybrid_search"]
    tools = [t for t in tools if t in ALL_TOOLS] or ["hybrid_search"]

    return {"category": category, "sub_questions": sub_questions, "tools": tools}


async def planner_node(state: AgentState) -> dict:
    async with trace_bus.stage(state["session_id"], "planner", to_stage="rewriter") as h:
        result = await plan(state["query"])
        h.set_metric("category", result["category"])
        h.set_metric("sub_question_count", len(result["sub_questions"]))
        h.set_output(f"category={result['category']} tools={result['tools']}")

    summary = f"Classified as {result['category']}, {len(result['sub_questions'])} sub-question(s)."
    return {
        **result,
        "agent_steps": record_step(state, "planner", summary),
    }


def route_after_planner(state: AgentState) -> str:
    category = state.get("category")
    if category == "out_of_scope":
        return "out_of_scope"
    if category == "summary":
        return "summarize"
    return "continue"


async def decline_node(state: AgentState) -> dict:
    """Short-circuits straight to a decline — no point running retrieval/synthesis for a
    question the Planner already determined is out of scope for this document."""
    answer = (
        "That's outside what I can help with for this document — I can only answer questions "
        "about the content that's been uploaded or ingested."
    )
    return {
        "answer": answer,
        "citations": [],
        "agent_steps": record_step(state, "planner", "Out of scope — declining without retrieval."),
    }
