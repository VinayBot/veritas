"""Synthesizer: answers from the retrieved context with inline [n] citations. Re-entered after
the Verifier flags unsupported claims, in which case the prompt asks for a corrected answer
instead of a fresh one.
"""

from __future__ import annotations

from app.agents.answer_style import style_for
from app.agents.citations import citation_markers
from app.agents.context_utils import UNTRUSTED_CONTEXT_SYSTEM_PROMPT, build_numbered_context
from app.agents.state import AgentState, Citation, record_step
from app.core.tracing import trace_bus
from app.council.service import run_council
from app.llm.client import LlmUnavailableError
from app.llm.models_config import get_model_config
from app.llm.router import complete_with_latency_budget

_SYNTH_PROMPT = (
    "Answer the question using ONLY the numbered context below. Cite sources inline using "
    "[1], [2], etc., matching the numbers below. If the context doesn't contain the answer, "
    "say you don't have enough information rather than guessing. {style}\n\n"
    "{context}\n\nQuestion: {query}\n\nAnswer:"
)

_REVISE_PROMPT = (
    "Your previous answer made claims that aren't supported by the context:\n{unsupported}\n\n"
    "Context:\n{context}\n\nQuestion: {query}\n\nPrevious answer: {previous_answer}\n\n"
    "Write a corrected answer that removes or qualifies the unsupported claims, keeping "
    "[n]-style citations for whatever remains supported. If nothing can be supported, say you "
    "don't have enough information. {style}"
)


async def synthesizer_node(state: AgentState) -> dict:
    retrieved = state.get("retrieved", [])
    context = build_numbered_context(retrieved)
    is_revision = state.get("verifier_verdict") == "revise"
    council_run_id = state.get("council_run_id")
    routing = state.get("routing")
    style = style_for(state.get("detail"))

    async with trace_bus.stage(
        state["session_id"], "synthesizer", from_stage="critic", to_stage="verifier"
    ) as h:
        # force_fast (the post-timeout retry — see docs/DECISIONS.md) always skips council: a
        # multi-model ensemble is the single most expensive thing this node can do, and the
        # whole point of this attempt is to be fast.
        use_council = bool(state.get("council")) and not state.get("force_fast")
        if use_council and not is_revision:
            query = state["query"]
            result = await run_council(state["session_id"], query, context, style)
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
                        style=style.instruction,
                    )
                else:
                    prompt = _SYNTH_PROMPT.format(
                        context=context, query=state["query"], style=style.instruction
                    )
                config = get_model_config()
                # Reproduced live (see docs/TROUBLESHOOTING.md): on revision, the default fast
                # model dropped the citation marker entirely and prefixed a self-contradicting
                # "I don't have enough information... however" hedge in front of an otherwise
                # correct, now-fully-supported answer — reproducible 2/2, while the stronger
                # council model kept the citation and dropped the hedge both times. A revision
                # is always a correction task, regardless of how simple the original query is.
                # force_fast overrides this: it specifically wants the fast default model even
                # on a revision pass, since it only exists to recover quickly from a timeout.
                # A quick reply stays on the fast generator; only a deep answer may be routed
                # to the stronger model.
                if use_council and is_revision:
                    # The council already deliberated once. A second full round costs five
                    # more model calls across three models — enough, with the agent's own
                    # steps, to exhaust the per-question call limit — so the chairman alone
                    # corrects the council's answer against the verifier's specific complaint.
                    force_model: str | None = config.chairman
                elif state.get("force_fast") or (style.prefer_fast_model and not is_revision):
                    force_model = config.generator
                elif is_revision:
                    force_model = config.stronger_model()
                else:
                    force_model = None
                routed = await complete_with_latency_budget(
                    prompt,
                    query_for_routing=state["query"],
                    system=UNTRUSTED_CONTEXT_SYSTEM_PROMPT,
                    max_tokens=style.max_tokens,
                    temperature=0.2,
                    force_primary_model=force_model,
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

    cited_markers = set(citation_markers(answer))
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
