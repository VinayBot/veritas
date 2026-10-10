"""Synthesizer: answers from the retrieved context with inline [n] citations. Re-entered after
the Verifier flags unsupported claims, in which case the prompt asks for a corrected answer
instead of a fresh one.
"""

from __future__ import annotations

import re

from app.agents.context_utils import UNTRUSTED_CONTEXT_SYSTEM_PROMPT, build_numbered_context
from app.agents.state import AgentState, Citation, record_step
from app.core.tracing import trace_bus
from app.council.service import run_council
from app.llm.client import LlmUnavailableError
from app.llm.router import complete_with_latency_budget

_SYNTH_PROMPT = (
    "Answer the question using ONLY the numbered context below. Cite sources inline using "
    "[1], [2], etc., matching the numbers below. If the context doesn't contain the answer, "
    "say you don't have enough information rather than guessing.\n\n"
    "{context}\n\nQuestion: {query}\n\nAnswer:"
)

_REVISE_PROMPT = (
    "Your previous answer made claims that aren't supported by the context:\n{unsupported}\n\n"
    "Context:\n{context}\n\nQuestion: {query}\n\nPrevious answer: {previous_answer}\n\n"
    "Write a corrected answer that removes or qualifies the unsupported claims, keeping "
    "[n]-style citations for whatever remains supported. If nothing can be supported, say you "
    "don't have enough information."
)

_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")


async def synthesizer_node(state: AgentState) -> dict:
    retrieved = state.get("retrieved", [])
    context = build_numbered_context(retrieved)
    is_revision = state.get("verifier_verdict") == "revise"
    council_run_id = state.get("council_run_id")
    routing = state.get("routing")

    async with trace_bus.stage(
        state["session_id"], "synthesizer", from_stage="critic", to_stage="verifier"
    ) as h:
        if state.get("council"):
            # Revisions still go through the full council, with the verifier's specific
            # complaint folded into the question so every member sees it — see docs/DECISIONS.md
            # on why council mode doesn't fall back to a single model on retry.
            query = state["query"]
            if is_revision:
                unsupported = "; ".join(state.get("unsupported_claims", []))
                query = (
                    f"{query}\n\n(A previous answer made unsupported claims: {unsupported}. "
                    "Avoid repeating them.)"
                )
            result = await run_council(state["session_id"], query, context)
            answer = result.final_answer
            council_run_id = result.id
            h.set_metric("council_members", result.members)
            h.set_metric("agreement_score", result.agreement_score)
        else:
            try:
                if is_revision:
                    prompt = _REVISE_PROMPT.format(
                        unsupported="\n".join(
                            f"- {c}" for c in state.get("unsupported_claims", [])
                        ),
                        context=context,
                        query=state["query"],
                        previous_answer=state.get("answer", ""),
                    )
                else:
                    prompt = _SYNTH_PROMPT.format(context=context, query=state["query"])
                routed = await complete_with_latency_budget(
                    prompt,
                    query_for_routing=state["query"],
                    system=UNTRUSTED_CONTEXT_SYSTEM_PROMPT,
                    max_tokens=500,
                    temperature=0.2,
                )
                answer = routed.answer
                routing = {
                    "primary_model": routed.primary_model,
                    "model_used": routed.model_used,
                    "fell_back": routed.fell_back,
                    "latency_ms": routed.latency_ms,
                }
                h.set_metric("model_used", routed.model_used)
                h.set_metric("fell_back", routed.fell_back)
            except LlmUnavailableError:
                answer = (
                    "I'm unable to generate an answer right now — the language model is "
                    "unavailable."
                )
        h.set_metric("revision", is_revision)
        h.set_output(answer[:200])

    cited_markers = {int(m) for m in _CITATION_MARKER_RE.findall(answer)}
    if not cited_markers and len(retrieved) == 1:
        # The model didn't emit a "[1]" marker, but with exactly one source there's no
        # ambiguity about where the answer came from — see docs/DECISIONS.md on why this
        # inference is sound for n=1 but deliberately not attempted for n>1.
        cited_markers = {1}
    citations: list[Citation] = [
        Citation(marker=i + 1, chunk_id=hit["chunk_id"], text=hit["text"][:300])
        for i, hit in enumerate(retrieved)
        if (i + 1) in cited_markers
    ]

    verb = "Revised the" if is_revision else "Synthesized an"
    summary = f"{verb} answer citing {len(citations)} source(s)."
    return {
        "answer": answer,
        "citations": citations,
        "agent_steps": record_step(state, "synthesizer", summary),
        "council_run_id": council_run_id,
        "routing": routing,
    }
