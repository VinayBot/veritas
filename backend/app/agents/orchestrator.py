"""Orchestrates one chat turn: semantic cache check -> run the selected RAG mode -> cache store
-> persist a report. "agentic" runs the full LangGraph state machine; "hybrid" and "graph" are
direct, non-agentic pipelines (one retrieval tool, one synthesis call) — simpler, cheaper
alternatives the brief says the user can select instead of the primary agentic mode.

Guardrails are Phase 6 stubs on every path (`guardian_out_node`) — Phase 7 replaces the stub
without this orchestration needing to change.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from app.agents.context_utils import UNTRUSTED_CONTEXT_SYSTEM_PROMPT, build_numbered_context
from app.agents.graph import get_agent_graph
from app.agents.guardian import guardian_out_node
from app.agents.models import ChatReport
from app.agents.state import AgentState, Citation, initial_state
from app.agents.tools import graph_traverse_tool, hybrid_search_tool
from app.core.db import session_scope
from app.core.tracing import trace_bus
from app.council.service import run_council
from app.evaluation.judge import citation_validity, score_faithfulness, score_relevancy
from app.guardrails.input import check_input
from app.guardrails.retrieval import scan_hits
from app.llm.client import LlmUnavailableError
from app.llm.router import complete_with_latency_budget
from app.retrieval import semantic_cache

VALID_MODES = ("agentic", "hybrid", "graph")
_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")

_DIRECT_SYNTH_PROMPT = (
    "Answer the question using ONLY the numbered context below. Cite sources inline using "
    "[1], [2], etc. If the context doesn't contain the answer, say you don't have enough "
    "information rather than guessing.\n\n{context}\n\nQuestion: {query}\n\nAnswer:"
)


@dataclass
class SynthesisResult:
    answer: str
    citations: list[Citation]
    council_run_id: str | None
    routing: dict[str, Any] | None


async def _direct_pipeline(
    session_id: str, query: str, hits: list[dict], council: bool = False
) -> SynthesisResult:
    context = build_numbered_context(hits)
    council_run_id: str | None = None
    routing: dict[str, Any] | None = None
    async with trace_bus.stage(session_id, "synthesizer", from_stage="retriever") as h:
        if council:
            result = await run_council(session_id, query, context)
            answer = result.final_answer
            council_run_id = result.id
            h.set_metric("council_members", result.members)
            h.set_metric("agreement_score", result.agreement_score)
        else:
            try:
                routed = await complete_with_latency_budget(
                    _DIRECT_SYNTH_PROMPT.format(context=context, query=query),
                    query_for_routing=query,
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
        h.set_output(answer[:200])

    cited = {int(m) for m in _CITATION_MARKER_RE.findall(answer)}
    if not cited and len(hits) == 1:
        cited = {1}  # unambiguous single-source case — see synthesizer.py / docs/DECISIONS.md
    citations: list[Citation] = [
        Citation(marker=i + 1, chunk_id=hit["chunk_id"], text=hit["text"][:300])
        for i, hit in enumerate(hits)
        if (i + 1) in cited
    ]
    return SynthesisResult(answer, citations, council_run_id, routing)


async def _run_non_agentic(
    session_id: str, query: str, document_id: str | None, mode: str, council: bool = False
) -> tuple[str, list[Citation], list[dict], str | None, dict[str, Any] | None]:
    async with trace_bus.stage(session_id, "retriever", to_stage="synthesizer") as h:
        if mode == "hybrid":
            hits = await hybrid_search_tool(query, document_id, k=5)
        else:
            hits = await graph_traverse_tool(query)
        hits = await scan_hits(hits, session_id, h.trace_id)
        h.set_metric("hit_count", len(hits))
        h.set_metric("flagged_count", sum(1 for hit in hits if hit.get("flagged_injection")))
        h.set_metric("mode", mode)

    synthesis = await _direct_pipeline(session_id, query, hits, council)
    steps = [
        {
            "node": "retriever",
            "summary": f"{mode.title()} retrieval found {len(hits)} piece(s) of evidence.",
        },
        {
            "node": "synthesizer",
            "summary": f"Synthesized an answer citing {len(synthesis.citations)} source(s).",
        },
    ]
    return synthesis.answer, synthesis.citations, steps, synthesis.council_run_id, synthesis.routing


async def _apply_output_guardrail(
    session_id: str, answer: str, citations: Sequence[Mapping[str, Any]], reveal_pii: bool
) -> tuple[str, Sequence[Mapping[str, Any]]]:
    # Citation is structurally a Mapping[str, Any] (it's a TypedDict), so anything this function
    # is actually called with already satisfies AgentState's declared `list[Citation]` — the
    # cast just tells mypy what's already true at every real call site.
    state: AgentState = {
        "session_id": session_id,
        "answer": answer,
        "citations": cast(list[Citation], list(citations)),
        "reveal_pii": reveal_pii,
        "agent_steps": [],
    }
    guarded = await guardian_out_node(state)
    return guarded.get("answer", answer), guarded.get("citations", citations)


async def _score_quality(
    query: str, answer: str, citations: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Reference-free quality scoring for a live chat turn — labelled "estimated" because there
    is no ground-truth answer to verify against (that only exists in the benchmark runner's
    synthetic eval set; see app/evaluation/judge.py and docs/DECISIONS.md)."""
    relevancy = await score_relevancy(answer, query)
    citation_score = citation_validity(answer, len(citations) or 1)
    faithfulness: float | None = None
    if citations:
        context = "\n\n".join(str(c.get("text", "")) for c in citations)
        faithfulness = await score_faithfulness(answer, context)
        confidence = (faithfulness + relevancy + citation_score) / 3
    else:
        confidence = (relevancy + citation_score) / 2
    return {
        "label": "estimated",
        "faithfulness": faithfulness,
        "relevancy": relevancy,
        "citation_validity": citation_score,
        "confidence": confidence,
    }


async def _persist_report(
    session_id: str,
    document_id: str | None,
    mode: str,
    query: str,
    answer: str,
    citations: Sequence[Mapping[str, Any]],
    agent_steps: list[dict],
    cache_hit: bool,
    council_run_id: str | None,
    routing: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    quality = await _score_quality(query, answer, citations)
    report_id = str(uuid.uuid4())
    async with session_scope() as session:
        session.add(
            ChatReport(
                id=report_id,
                session_id=session_id,
                document_id=document_id,
                mode=mode,
                query=query,
                answer=answer,
                citations=citations,
                agent_steps=agent_steps,
                cache_hit=cache_hit,
                quality=quality,
                council_run_id=council_run_id,
                routing=routing,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return report_id, quality


async def run_chat_turn(
    query: str,
    document_id: str | None,
    mode: str = "agentic",
    reveal_pii: bool = False,
    session_id: str | None = None,
    council: bool = False,
    on_session_started: Callable[[str, bool], Awaitable[None]] | None = None,
) -> dict:
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown chat mode: {mode!r}. Valid: {VALID_MODES}")

    session_id = session_id or str(uuid.uuid4())
    cached = await semantic_cache.lookup(query, document_id, mode)
    # Lets the caller (the SSE route) learn session_id/cache_hit the moment they're known —
    # right after this one cheap cache lookup — instead of only once the whole turn finishes.
    # Without this, the frontend's Architecture tab can't subscribe to this session's trace
    # feed until the turn is already over, so a brand-new conversation's first message would
    # only ever show its pipeline retroactively (a sudden history replay), never live. See
    # docs/TROUBLESHOOTING.md.
    if on_session_started is not None:
        await on_session_started(session_id, cached is not None)
    council_run_id: str | None = None
    routing: dict[str, Any] | None = None

    if cached is not None:
        # Deliberately skipped on a cache hit: a fresh *input* guardrail pass (the matched past
        # query already passed one, and the near-identical-query threshold is 0.96 — see
        # docs/DECISIONS.md). The *output* guardrail still runs on every cache hit, unconditionally.
        # Council also doesn't re-run — the cached answer was already final, nothing new to vote on.
        async with trace_bus.stage(session_id, "semantic_cache", to_stage="guardian_out") as h:
            h.set_metric("cache_hit", True)
            h.set_output(f"Served from cache (matched: {cached.query!r})")
        answer, citations = await _apply_output_guardrail(
            session_id, cached.answer, cached.citations, reveal_pii
        )
        agent_steps = [
            {"node": "semantic_cache", "summary": f"Served from cache (matched: {cached.query!r})"}
        ]
    elif mode == "agentic":
        # guardian_in/guardian_out both run *inside* the graph for this mode.
        state = initial_state(query, session_id, document_id, reveal_pii, council)
        result = await get_agent_graph().ainvoke(state)
        answer = result.get("answer", "")
        citations = result.get("citations", [])
        agent_steps = result.get("agent_steps", [])
        council_run_id = result.get("council_run_id")
        routing = result.get("routing")
        if result.get("guardrail_status") != "block":
            await semantic_cache.store(query, document_id, mode, answer, citations)
    else:
        async with trace_bus.stage(session_id, "guardian_in", to_stage="retriever") as h:
            input_result = await check_input(query, session_id, h.trace_id)
            h.set_metric("decision", input_result.decision)
            if input_result.decision == "block":
                h.mark_blocked()

        if input_result.decision == "block":
            answer, citations, agent_steps = (
                "I can't help with that request — it was flagged by an input safety check.",
                [],
                [
                    {
                        "node": "guardian_in",
                        "summary": f"Input guardrail: blocked ({input_result.rule}).",
                    }
                ],
            )
        else:
            answer, citations, agent_steps, council_run_id, routing = await _run_non_agentic(
                session_id, query, document_id, mode, council
            )
            agent_steps = [
                {
                    "node": "guardian_in",
                    "summary": f"Input guardrail: allowed ({input_result.rule}).",
                }
            ] + agent_steps

        answer, citations = await _apply_output_guardrail(session_id, answer, citations, reveal_pii)
        if input_result.decision != "block":
            await semantic_cache.store(query, document_id, mode, answer, citations)

    report_id, quality = await _persist_report(
        session_id,
        document_id,
        mode,
        query,
        answer,
        citations,
        agent_steps,
        cached is not None,
        council_run_id,
        routing,
    )

    return {
        "session_id": session_id,
        "answer": answer,
        "citations": citations,
        "agent_steps": agent_steps,
        "report_id": report_id,
        "cache_hit": cached is not None,
        "quality": quality,
        "council_run_id": council_run_id,
        "routing": routing,
    }
