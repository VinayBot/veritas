"""Guardian: wraps the agent graph's input and output with the real three-layer guardrail
system (app/guardrails/). Phase 6 had these as pass-through stubs with this exact signature —
Phase 7 fills them in without touching the graph topology or the orchestrator.
"""

from __future__ import annotations

from app.agents.state import AgentState, record_step
from app.core.tracing import trace_bus
from app.guardrails.input import check_input
from app.guardrails.output import check_output


async def guardian_in_node(state: AgentState) -> dict:
    async with trace_bus.stage(
        state["session_id"], "guardian_in", from_stage="client", to_stage="planner"
    ) as h:
        result = await check_input(state["query"], state["session_id"], h.trace_id)
        h.set_metric("decision", result.decision)
        h.set_metric("rule", result.rule)
        h.set_output(f"{result.decision}: {result.reason}")
        if result.decision == "block":
            h.mark_blocked()

    summary = f"Input guardrail: {result.decision} ({result.rule})."
    # Same vocabulary as check_output's GuardrailResult.decision ("allow" | "redact" | "block" |
    # "escalate") throughout — guardian_in and guardian_out used to disagree ("blocked" vs.
    # "block"), which was silently masking the overwrite bug fixed below (see docs/DECISIONS.md).
    update: dict = {"agent_steps": record_step(state, "guardian_in", summary)}
    if result.decision == "block":
        update["guardrail_status"] = "block"
        update["guardrail_reason"] = result.reason
        update["answer"] = (
            "I can't help with that request — it was flagged by an input safety check."
        )
        update["citations"] = []
    return update


def route_after_guardian_in(state: AgentState) -> str:
    return "blocked" if state.get("guardrail_status") == "block" else "continue"


async def guardian_out_node(state: AgentState) -> dict:
    # If guardian_in already blocked this turn, the "answer" here is just our own canned
    # decline message — there's nothing meaningful left to re-check, and running check_output
    # on it anyway previously caused a real bug: an independent output-layer judgment (e.g.
    # "no citations on this message") would overwrite the already-correct "block" decision
    # with something else entirely (observed: it became "escalate"). Short-circuit instead.
    if state.get("guardrail_status") == "block":
        async with trace_bus.stage(
            state["session_id"], "guardian_out", from_stage="verifier", to_stage="client"
        ) as h:
            h.set_metric("decision", "block")
            h.set_output("Input was already blocked — passing the decline through unchanged.")
            h.mark_blocked()
        summary = "Output guardrail: skipped (input already blocked this turn)."
        return {"agent_steps": record_step(state, "guardian_out", summary)}

    async with trace_bus.stage(
        state["session_id"], "guardian_out", from_stage="verifier", to_stage="client"
    ) as h:
        result = await check_output(
            state.get("answer", ""),
            state.get("citations", []),
            state["session_id"],
            h.trace_id,
            reveal_pii=state.get("reveal_pii", False),
            question=state.get("query"),
            sources=[str(hit.get("text", "")) for hit in state.get("retrieved", [])],
        )
        h.set_metric("decision", result.decision)
        h.set_metric("rule", result.rule)
        h.set_output(f"{result.decision}: {result.reason}")
        if result.decision == "block":
            h.mark_blocked()

    summary = f"Output guardrail: {result.decision} ({result.rule})."
    update: dict = {
        "guardrail_status": result.decision,
        "guardrail_reason": result.reason,
        "answer": result.answer,
        "agent_steps": record_step(state, "guardian_out", summary),
    }
    if result.decision == "block":
        update["citations"] = []
    return update
