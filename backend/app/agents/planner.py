"""Planner/Router: classifies the query, decomposes multi-part questions into sub-questions,
and picks which retrieval tools the Retriever node should use.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic import BaseModel, ValidationError, field_validator

from app.agents.state import AgentState, record_step
from app.core.config import get_settings
from app.core.tracing import trace_bus
from app.llm.client import LlmUnavailableError, complete, complete_tool_call
from app.llm.json_utils import extract_json_object

logger = logging.getLogger(__name__)

CATEGORIES = ("factoid", "multi_hop", "comparison", "summary", "pii_lookup", "out_of_scope")
ALL_TOOLS = ("hybrid_search", "graph_traverse", "pii_vault_lookup", "metadata_filter")

_PLANNER_PROMPT = """Classify this question and decide how to answer it. Return ONLY a JSON \
object, no other text, no markdown fences, with exactly these keys:
- "category": one of {categories}. Use "summary" for any broad question that asks for an \
overview, history, or general account spanning the whole document (e.g. "history of X", \
"tell me about X", "summarize X") rather than one specific fact — these need wide, diverse \
retrieval across the document, not a single targeted lookup, and route differently. A \
question about what something is or how it works ("what is X", "how does X work") is \
"factoid": it is answered by the passages about X, not by a sample of the whole document.
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


PLAN_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "plan_retrieval",
        "description": (
            "Record how to answer the user's question about their document: its category, the "
            "sub-questions to look up, and which retrieval tools to use."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": list(CATEGORIES),
                    "description": (
                        "summary: an overview, history or 'tell me about' question spanning "
                        "the document. factoid: one fact, including 'what is X' and 'how does "
                        "X work'. multi_hop: needs several facts combined. comparison: compares "
                        "things. pii_lookup: asks for a person's contact details. "
                        "out_of_scope: unrelated to any document."
                    ),
                },
                "sub_questions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "1-4 self-contained questions; just the question if simple.",
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(ALL_TOOLS)},
                    "description": (
                        "hybrid_search for almost everything; graph_traverse when entities "
                        "must be connected; pii_vault_lookup for contact details."
                    ),
                },
            },
            "required": ["category", "sub_questions", "tools"],
        },
    },
}


# The same guidance the JSON prompt gives, for the tool call: without it the model sent
# narrow questions ("What are the types of X?") down the slower document-wide summary route.
_TOOL_PROMPT = (
    "Call plan_retrieval for this question about the user's document.\n"
    "- category 'summary' ONLY for an overview, history or 'tell me about X' question that "
    "spans the whole document.\n"
    "- category 'factoid' for one fact or definition, including 'what is X', 'how does X "
    "work' and 'what are the types of X'.\n"
    "- 'multi_hop' when several facts must be combined, 'comparison' when things are "
    "compared, 'pii_lookup' for a person's contact details, 'out_of_scope' when unrelated "
    "to any document.\n"
    "- sub_questions: just the question itself unless it has several separate parts.\n"
    "- tools: hybrid_search, plus graph_traverse only when entities must be connected.\n\n"
    "Question: {query}"
)


class PlanArgs(BaseModel):
    """Validates a native tool call's arguments. Small models send lists as JSON strings or
    null; those shapes are repaired here rather than rejected."""

    category: Literal["factoid", "multi_hop", "comparison", "summary", "pii_lookup", "out_of_scope"]
    sub_questions: list[str] = []
    tools: list[str] = []

    @field_validator("sub_questions", "tools", mode="before")
    @classmethod
    def _listify(cls, value: Any) -> list:
        import json

        if value is None:
            return []
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except ValueError:
                return [value] if value.strip() else []
            return decoded if isinstance(decoded, list) else [str(decoded)]
        return list(value)


def _normalise(category: str, sub_questions: list, tools: list, query: str) -> dict:
    subs = [str(q) for q in sub_questions if str(q).strip()][:4] or [query]
    picked = [t for t in tools if t in ALL_TOOLS]
    if category == "pii_lookup":
        picked = picked or ["pii_vault_lookup"]
    elif "hybrid_search" not in picked:
        picked = ["hybrid_search", *picked]
    return {"category": category, "sub_questions": subs, "tools": picked}


async def plan_with_tool_call(query: str, model: str | None = None) -> dict | None:
    """The plan from a native tool call, or None when the model gave no valid one."""
    try:
        arguments = await complete_tool_call(
            _TOOL_PROMPT.format(query=query), PLAN_TOOL, model=model
        )
    except LlmUnavailableError:
        return None
    if not arguments:
        return None
    try:
        args = PlanArgs.model_validate(arguments)
    except ValidationError:
        return None
    return {**_normalise(args.category, args.sub_questions, args.tools, query), "via": "tool_call"}


async def plan(query: str, model: str | None = None, mode: str | None = None) -> dict:
    """PLANNER_MODE picks the method. "tool_call": the model's native tool calling, falling back
    to the JSON prompt when it gives no valid call. "json" (the default): the JSON prompt.
    Measured on tests/fixtures/planner_routing.json with llama3.2:3b (`make planner-eval`), the
    JSON prompt routed more questions correctly, so it is the default for that model; a
    model that does better with native tools is one setting away. Keyword heuristics apply
    when no model is reachable."""
    if (mode or get_settings().planner_mode) == "tool_call":
        planned = await plan_with_tool_call(query, model)
        if planned is not None:
            return planned
    return {**await _plan_with_json(query, model), "via": "json"}


async def _plan_with_json(query: str, model: str | None = None) -> dict:
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
        via = result.pop("via", "heuristic")
        h.set_metric("planned_via", via)
        h.set_metric("category", result["category"])
        h.set_metric("sub_question_count", len(result["sub_questions"]))
        h.set_output(f"category={result['category']} tools={result['tools']}")

    summary = (
        f"Classified as {result['category']}, {len(result['sub_questions'])} sub-question(s), "
        f"tools {', '.join(result['tools'])} (planned by {via.replace('_', ' ')})."
    )
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
