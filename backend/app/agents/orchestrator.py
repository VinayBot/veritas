"""Orchestrates one chat turn.

A turn has two halves, kept apart on purpose:

1. **Answer** (`produce_turn`): semantic-cache check, then the chosen RAG strategy — either
   the LangGraph agent (`agentic`, `council`) or a direct pipeline (one retrieval pass
   described by the strategy's plan, one generation), with the input and output guardrails
   on both paths.
2. **Report** (`finalize_turn`): judge the answer (relevancy, faithfulness, sentence-level
   grounding) and persist everything the UI shows about the turn.

The split is what makes a quick answer quick: the person sees the answer as soon as half 1
finishes, and the scoring in half 2 — several more model calls — happens after, not before.
`run_chat_turn` runs both in sequence for callers that just want the result (tests, scripts);
`run_chat_turn_tracked` streams half 1's output to the client first.

`run_chat_turn_tracked` also owns everything a persisted run needs that the turn itself does
not know about: an overall timeout, a total LLM-call budget, and one automatic retry with the
fast model if the first attempt trips either (Fix 1 — see docs/DECISIONS.md).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select

from app.agents.answer_style import resolve_detail, style_for, tidy_answer
from app.agents.citations import citation_markers
from app.agents.context_utils import UNTRUSTED_CONTEXT_SYSTEM_PROMPT, build_numbered_context
from app.agents.graph import get_agent_graph
from app.agents.guardian import guardian_out_node
from app.agents.models import ChatReport
from app.agents.runs import record_event, relay_trace_to_run, set_run_status
from app.agents.state import AgentState, Citation, initial_state
from app.chunking.models import ChunkRow
from app.core.config import get_settings
from app.core.db import session_scope
from app.core.tracing import trace_bus
from app.council.service import run_council
from app.evaluation.grounding import ground_answer
from app.evaluation.judge import citation_validity, judge_model, score_all
from app.guardrails.input import check_input
from app.guardrails.retrieval import scan_hits
from app.llm import client as llm_client
from app.llm.client import (
    LlmBudgetExceededError,
    LlmUnavailableError,
    clear_llm_call_budget,
    reset_llm_call_budget,
)
from app.llm.models_config import get_model_config
from app.llm.router import complete_with_latency_budget
from app.rag_engines import execute as strategy_execute
from app.rag_engines.base import StrategySpec
from app.rag_engines.registry import UnknownStrategyError, get_strategy
from app.retrieval import semantic_cache
from app.retrieval import service as retrieval_service
from app.retrieval.index_guard import IndexMismatchError, assert_index_current

logger = logging.getLogger(__name__)


_DIRECT_SYNTH_PROMPT = (
    "Answer the question using ONLY the numbered context below. Cite sources inline using "
    "[1], [2], etc. If the context doesn't contain the answer, say you don't have enough "
    "information rather than guessing. {style}\n\n{context}\n\nQuestion: {query}\n\nAnswer:"
)

# How long the post-answer scoring may take before the report is saved without it.
SCORING_TIMEOUT_SECONDS = 120.0


@dataclass
class Turn:
    """Everything known about a turn once its answer exists (before it is judged)."""

    session_id: str
    document_id: str | None
    strategy: str
    detail: str
    query: str
    answer: str
    citations: list[dict[str, Any]]
    agent_steps: list[dict[str, Any]]
    outcome: str  # "done" | "blocked" | "abstained"
    cache_hit: bool = False
    council_run_id: str | None = None
    routing: dict[str, Any] | None = None
    retrieved: list[dict[str, Any]] = field(default_factory=list)
    funnels: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    timings: list[dict[str, Any]] = field(default_factory=list)
    loops: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0

    def summary(self) -> dict[str, Any]:
        """What the client needs the moment the answer is ready."""
        return {
            "strategy": self.strategy,
            "detail": self.detail,
            "latency_ms": round(self.latency_ms, 1),
            "cache_hit": self.cache_hit,
            "outcome": self.outcome,
            "usage": self.usage,
        }


def _citations_from(answer: str, hits: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    cited = set(citation_markers(answer))
    if not cited and len(hits) == 1:
        cited = {1}  # unambiguous single-source case — see synthesizer.py / docs/DECISIONS.md
    return [
        dict(Citation(marker=i + 1, chunk_id=hit["chunk_id"], text=hit["text"][:300]))
        for i, hit in enumerate(hits)
        if (i + 1) in cited
    ]


async def _synthesize_direct(
    session_id: str, query: str, hits: list[dict], spec: StrategySpec, detail: str, force_fast: bool
) -> tuple[str, str | None, dict[str, Any] | None]:
    """One generation over the retrieved context. Returns (answer, council_run_id, routing)."""
    style = style_for(detail)
    context = build_numbered_context(hits)
    council_run_id: str | None = None
    routing: dict[str, Any] | None = None
    async with trace_bus.stage(
        session_id, "synthesizer", from_stage="retriever", to_stage="guardian_out"
    ) as h:
        if spec.council and not force_fast:
            result = await run_council(session_id, query, context, style)
            answer = result.final_answer
            council_run_id = result.id
            h.set_metric("council_members", result.members)
            h.set_metric("agreement_score", result.agreement_score)
        else:
            try:
                routed = await complete_with_latency_budget(
                    _DIRECT_SYNTH_PROMPT.format(
                        context=context, query=query, style=style.instruction
                    ),
                    query_for_routing=query,
                    system=UNTRUSTED_CONTEXT_SYSTEM_PROMPT,
                    max_tokens=style.max_tokens,
                    temperature=0.2,
                    stream=True,
                    # A quick reply never waits on the slower, stronger model.
                    force_primary_model=(
                        get_model_config().generator
                        if force_fast or style.prefer_fast_model
                        else None
                    ),
                )
                answer = tidy_answer(routed.answer, detail)
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
        h.set_metric("detail", detail)
        h.set_output(answer[:200])
    return answer, council_run_id, routing


async def _apply_output_guardrail(
    session_id: str,
    answer: str,
    citations: Sequence[Mapping[str, Any]],
    reveal_pii: bool,
    already_blocked: bool = False,
    query: str = "",
) -> tuple[str, list[dict[str, Any]], str]:
    state: AgentState = {
        "session_id": session_id,
        "query": query,
        "answer": answer,
        "citations": cast(list[Citation], list(citations)),
        "reveal_pii": reveal_pii,
        "agent_steps": [],
    }
    if already_blocked:
        # guardian_out_node short-circuits on guardrail_status == "block"; without this, its
        # missing-citations check fires on our own decline message and overwrites the block
        # with "escalate" (see docs/DECISIONS.md).
        state["guardrail_status"] = "block"
    guarded = await guardian_out_node(state)
    decision = guarded.get("guardrail_status", "allow")
    kept = [dict(c) for c in guarded.get("citations", citations)]
    return guarded.get("answer", answer), kept, decision


async def _run_direct(
    spec: StrategySpec,
    session_id: str,
    query: str,
    document_id: str | None,
    reveal_pii: bool,
    detail: str,
    force_fast: bool,
) -> dict[str, Any]:
    async with trace_bus.stage(
        session_id, "guardian_in", from_stage="client", to_stage="retriever"
    ) as h:
        input_result = await check_input(query, session_id, h.trace_id)
        h.set_metric("decision", input_result.decision)
        if input_result.decision == "block":
            h.mark_blocked()

    hits: list[dict] = []
    council_run_id: str | None = None
    routing: dict[str, Any] | None = None
    if input_result.decision == "block":
        answer = "I can't help with that request — it was flagged by an input safety check."
        citations: list[dict[str, Any]] = []
        steps = [
            {"node": "guardian_in", "summary": f"Input guardrail: blocked ({input_result.rule})."}
        ]
    else:
        async with trace_bus.stage(
            session_id, "retriever", from_stage="guardian_in", to_stage="synthesizer"
        ) as h:
            hits = await strategy_execute.retrieve(spec, query, document_id)
            hits = await scan_hits(hits, session_id, h.trace_id)
            h.set_metric("hit_count", len(hits))
            h.set_metric("flagged_count", sum(1 for hit in hits if hit.get("flagged_injection")))
            h.set_metric("strategy", spec.id)
            h.set_output(f"{len(hits)} chunks via {spec.display_name}")
        answer, council_run_id, routing = await _synthesize_direct(
            session_id, query, hits, spec, detail, force_fast
        )
        citations = _citations_from(answer, hits)
        steps = [
            {"node": "guardian_in", "summary": f"Input guardrail: allowed ({input_result.rule})."},
            {
                "node": "retriever",
                "summary": f"{spec.display_name} retrieval found {len(hits)} piece(s) of evidence.",
            },
            {
                "node": "synthesizer",
                "summary": f"Wrote a {detail} answer citing {len(citations)} source(s).",
            },
        ]

    answer, citations, out_decision = await _apply_output_guardrail(
        session_id,
        answer,
        citations,
        reveal_pii,
        already_blocked=input_result.decision == "block",
        query=query,
    )
    return {
        "answer": answer,
        "citations": citations,
        "agent_steps": steps,
        "retrieved": hits,
        "council_run_id": council_run_id,
        "routing": routing,
        "outcome": "blocked" if out_decision == "block" else "done",
        "loops": {},
    }


async def _run_agentic(
    spec: StrategySpec,
    session_id: str,
    query: str,
    document_id: str | None,
    reveal_pii: bool,
    detail: str,
    force_fast: bool,
) -> dict[str, Any]:
    # guardian_in and guardian_out both run inside the graph.
    state = initial_state(
        query,
        session_id,
        document_id,
        reveal_pii,
        spec.council and not force_fast,
        force_fast,
        detail,
    )
    result = await get_agent_graph().ainvoke(state)
    if result.get("guardrail_status") == "block":
        outcome = "blocked"
    elif result.get("verifier_verdict") == "abstain":
        outcome = "abstained"
    else:
        outcome = "done"
    return {
        "answer": result.get("answer", ""),
        "citations": [dict(c) for c in result.get("citations", [])],
        "agent_steps": result.get("agent_steps", []),
        "retrieved": [dict(h) for h in result.get("retrieved", [])],
        "council_run_id": result.get("council_run_id"),
        "routing": result.get("routing"),
        "outcome": outcome,
        "loops": {
            "critic_loops": result.get("loop_count", 0),
            "revisions": result.get("revise_count", 0),
        },
    }


def _timings_since(session_id: str, start_index: int) -> list[dict[str, Any]]:
    """Finished stages of this turn, in order, straight from the trace bus."""
    return [
        {
            "stage": e.stage,
            "status": str(e.status),
            "started_at": e.started_at.isoformat(),
            "duration_ms": e.duration_ms,
            "input_preview": e.input_preview,
            "output_preview": e.output_preview,
            "metrics": e.metrics,
        }
        for e in trace_bus.history(session_id)[start_index:]
        if e.duration_ms is not None
    ]


async def answer_question(
    query: str,
    document_id: str | None,
    strategy_id: str,
    *,
    session_id: str,
    reveal_pii: bool = False,
    detail: str = "brief",
    force_fast: bool = False,
) -> Turn:
    """Runs one strategy end to end and returns its answer with what it cost. No cache, no
    report: this is the part evaluation and comparison share with live chat."""
    spec = get_strategy(strategy_id)
    await assert_index_current(document_id)
    start_index = len(trace_bus.history(session_id))
    usage = llm_client.start_usage_collection()
    funnels = retrieval_service.start_funnel_collection()
    started = time.perf_counter()
    try:
        runner = _run_agentic if spec.kind == "agentic" else _run_direct
        result = await runner(spec, session_id, query, document_id, reveal_pii, detail, force_fast)
    finally:
        llm_client.stop_usage_collection()
        retrieval_service.stop_funnel_collection()
    return Turn(
        session_id=session_id,
        document_id=document_id,
        strategy=spec.id,
        detail=detail,
        query=query,
        answer=result["answer"],
        citations=result["citations"],
        agent_steps=result["agent_steps"],
        outcome=result["outcome"],
        council_run_id=result["council_run_id"],
        routing=result["routing"],
        retrieved=result["retrieved"],
        funnels=list(funnels),
        usage=dict(usage),
        timings=_timings_since(session_id, start_index),
        loops=result["loops"],
        latency_ms=(time.perf_counter() - started) * 1000,
    )


def cache_scope(strategy: str, detail: str) -> str:
    # The answer model is part of the key: after switching models, a cached answer written
    # by the previous one is not served as if the new one had produced it.
    return f"{strategy}:{detail}:{get_model_config().generator}"


async def produce_turn(
    query: str,
    document_id: str | None,
    strategy: str | None = None,
    *,
    reveal_pii: bool = False,
    session_id: str | None = None,
    detail: str | None = None,
    force_fast: bool = False,
    on_session_started: Callable[[str, bool], Awaitable[None]] | None = None,
) -> Turn:
    """Half 1: the answer. Raises UnknownStrategyError for an unknown strategy id."""
    if strategy is None:
        from app.rag_engines.document_strategy import effective_strategy

        strategy = (await effective_strategy(document_id))[0]
    spec = get_strategy(strategy)
    resolved_detail = resolve_detail(query, detail)
    session_id = session_id or str(uuid.uuid4())
    await assert_index_current(document_id)
    scope = cache_scope(spec.id, resolved_detail)
    cached = await semantic_cache.lookup(query, document_id, scope)
    # Lets the caller learn session_id / cache_hit right after this one cheap lookup, so the
    # Architecture tab can subscribe to the trace before the turn is over.
    if on_session_started is not None:
        await on_session_started(session_id, cached is not None)

    if cached is not None:
        # The matched question already passed the input guardrail (similarity threshold 0.96);
        # the output guardrail still runs on every cache hit.
        started = time.perf_counter()
        start_index = len(trace_bus.history(session_id))
        async with trace_bus.stage(session_id, "semantic_cache", to_stage="guardian_out") as h:
            h.set_metric("cache_hit", True)
            h.set_output(f"Served from cache (matched: {cached.query!r})")
        answer, citations, decision = await _apply_output_guardrail(
            session_id, cached.answer, cached.citations, reveal_pii, query=query
        )
        return Turn(
            session_id=session_id,
            document_id=document_id,
            strategy=spec.id,
            detail=resolved_detail,
            query=query,
            answer=answer,
            citations=citations,
            agent_steps=[
                {
                    "node": "semantic_cache",
                    "summary": f"Served from cache (matched: {cached.query!r})",
                }
            ],
            outcome="blocked" if decision == "block" else "done",
            cache_hit=True,
            usage={"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "by_model": {}},
            timings=_timings_since(session_id, start_index),
            latency_ms=(time.perf_counter() - started) * 1000,
        )

    turn = await answer_question(
        query,
        document_id,
        spec.id,
        session_id=session_id,
        reveal_pii=reveal_pii,
        detail=resolved_detail,
        force_fast=force_fast,
    )
    if turn.outcome != "blocked":
        await semantic_cache.store(query, document_id, scope, turn.answer, turn.citations)
    return turn


async def _measure_all(calls: list[Awaitable[Any]]) -> list[Any]:
    """Judge calls side by side on the 16 GB tier, one after another on 8 GB."""
    if get_settings().hardware_tier == "8gb":
        return [await c for c in calls]
    return list(await asyncio.gather(*calls))


async def score_quality(turn: Turn) -> dict[str, Any]:
    """Reference-free scoring of a live answer — labelled "estimated" because there is no
    ground-truth answer to verify against. A value that could not be measured is None, and
    `confidence` is the mean of the ones that were."""
    citation_score = citation_validity(turn.answer, len(turn.citations) or 1)
    # Grounding is judged against everything the model was shown, faithfulness against what
    # it chose to cite.
    shown_context = "\n\n".join(str(h.get("text", "")) for h in turn.retrieved) or "\n\n".join(
        str(c.get("text", "")) for c in turn.citations
    )
    cited_context = "\n\n".join(str(c.get("text", "")) for c in turn.citations)

    async def judged() -> dict[str, float | None]:
        # Relevancy and faithfulness from one judge call.
        return await score_all(
            turn.answer, turn.query, context=cited_context if turn.citations else None
        )

    async def grounding() -> dict[str, Any] | None:
        if turn.outcome == "blocked" or not shown_context.strip():
            return None
        report = await ground_answer(turn.answer, shown_context, model=judge_model())
        return report.to_dict() if report else None

    scores, grounded = await _measure_all([judged(), grounding()])
    relevancy, faith = scores["relevancy"], scores["faithfulness"]
    measured = [v for v in (faith, relevancy, citation_score) if v is not None]
    return {
        "label": "estimated",
        "faithfulness": faith,
        "relevancy": relevancy,
        "citation_validity": citation_score,
        "grounding": grounded,
        "confidence": sum(measured) / len(measured) if measured else None,
        "judge_model": judge_model(),
    }


def unmeasured_quality(reason: str) -> dict[str, Any]:
    return {
        "label": "estimated",
        "faithfulness": None,
        "relevancy": None,
        "citation_validity": None,
        "grounding": None,
        "confidence": None,
        "judge_model": judge_model(),
        "not_measured_reason": reason,
    }


async def _retrieval_record(turn: Turn) -> dict[str, Any]:
    """The funnel (how many candidates each step saw) and, for every chunk in the context,
    its scores, where it came from in the document, and whether the answer cited it."""
    ids = [h["chunk_id"] for h in turn.retrieved]
    rows: dict[str, Any] = {}
    if ids:
        async with session_scope() as session:
            result = await session.execute(
                select(
                    ChunkRow.chunk_id, ChunkRow.section_path, ChunkRow.page, ChunkRow.strategy
                ).where(ChunkRow.chunk_id.in_(ids))
            )
            rows = {r[0]: r for r in result.all()}
    cited = {c["chunk_id"]: c["marker"] for c in turn.citations}
    chunks = []
    for position, hit in enumerate(turn.retrieved, start=1):
        row = rows.get(hit["chunk_id"])
        chunks.append(
            {
                "position": position,
                "chunk_id": hit["chunk_id"],
                "text": hit["text"],
                "score": hit.get("score"),
                "source": hit.get("source"),
                "found_by": hit.get("found_by"),
                "dense_rank": hit.get("dense_rank"),
                "sparse_rank": hit.get("sparse_rank"),
                "rerank_score": hit.get("rerank_score"),
                "section_path": row[1] if row else None,
                "page": row[2] if row else None,  # None: no parser records page numbers yet
                "chunking": row[3] if row else None,
                "used": hit["chunk_id"] in cited,
                "citation_marker": cited.get(hit["chunk_id"]),
                "flagged_injection": bool(hit.get("flagged_injection")),
            }
        )
    funnel: dict[str, Any] | None = None
    if turn.funnels:
        keys = ("dense_candidates", "sparse_candidates", "after_fusion", "after_rerank", "returned")
        funnel = {"searches": len(turn.funnels)}
        for key in keys:
            values = [f[key] for f in turn.funnels if key in f]
            funnel[key] = sum(values) if values else None
        funnel["in_context"] = len(turn.retrieved)
        funnel["used_in_answer"] = sum(1 for c in chunks if c["used"])
    return {"funnel": funnel, "chunks": chunks}


async def finalize_turn(
    turn: Turn, *, attempt: int = 1, score: bool = True
) -> tuple[str, dict[str, Any]]:
    """Half 2: judge the answer and persist the report. Returns (report_id, quality)."""
    if not score:
        quality = unmeasured_quality("Scoring was skipped for this turn.")
    else:
        try:
            quality = await asyncio.wait_for(score_quality(turn), timeout=SCORING_TIMEOUT_SECONDS)
        except TimeoutError:
            quality = unmeasured_quality("The judge model did not answer in time.")

    config = get_model_config()
    usage = dict(turn.usage or {})
    usage["models"] = {
        "generator": (turn.routing or {}).get("model_used") or config.generator,
        "judge": config.judge,
        "embedding": config.embedding,
        "reranker": config.reranker,
    }
    report_id = str(uuid.uuid4())
    async with session_scope() as session:
        session.add(
            ChatReport(
                id=report_id,
                session_id=turn.session_id,
                document_id=turn.document_id,
                mode=turn.strategy,
                strategy=turn.strategy,
                detail=turn.detail,
                outcome=turn.outcome,
                query=turn.query,
                answer=turn.answer,
                citations=turn.citations,
                agent_steps=turn.agent_steps,
                cache_hit=turn.cache_hit,
                quality=quality,
                council_run_id=turn.council_run_id,
                routing=turn.routing,
                latency_ms=turn.latency_ms,
                usage=usage,
                retrieval=await _retrieval_record(turn),
                timings=turn.timings,
                loops={**turn.loops, "attempt": attempt},
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return report_id, quality


async def run_chat_turn(
    query: str,
    document_id: str | None,
    strategy: str | None = None,
    reveal_pii: bool = False,
    session_id: str | None = None,
    detail: str | None = None,
    force_fast: bool = False,
    score: bool = True,
) -> dict:
    """Both halves in sequence, for callers that want the finished result."""
    turn = await produce_turn(
        query,
        document_id,
        strategy,
        reveal_pii=reveal_pii,
        session_id=session_id,
        detail=detail,
        force_fast=force_fast,
    )
    report_id, quality = await finalize_turn(turn, score=score)
    return {
        "session_id": turn.session_id,
        "strategy": turn.strategy,
        "detail": turn.detail,
        "answer": turn.answer,
        "citations": turn.citations,
        "agent_steps": turn.agent_steps,
        "report_id": report_id,
        "cache_hit": turn.cache_hit,
        "quality": quality,
        "council_run_id": turn.council_run_id,
        "routing": turn.routing,
        "outcome": turn.outcome,
        "latency_ms": turn.latency_ms,
        "usage": turn.usage,
    }


class _LiveTokens:
    """Relays text to the run's event log while the model is still writing it."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.sent = ""
        self._buffer = ""

    async def __call__(self, piece: str) -> None:
        self._buffer += piece
        if len(self._buffer) >= 12:
            await self.flush()

    async def flush(self) -> None:
        if self._buffer:
            chunk, self._buffer = self._buffer, ""
            self.sent += chunk
            await record_event(self.run_id, "token", chunk)


async def _emit_answer(run_id: str, turn: Turn, live: _LiveTokens | None = None) -> None:
    if live is not None:
        await live.flush()
    if live is not None and live.sent.strip() == turn.answer.strip():
        pass  # already on the reader's screen, word for word
    elif live is not None and live.sent:
        # What was streamed is not the final text (a retry, or the output guardrail redacted
        # or declined it): the client swaps in the final answer.
        await record_event(run_id, "replace", turn.answer)
    else:
        words = turn.answer.split(" ")
        buffer = ""
        for i, word in enumerate(words):
            buffer += word + (" " if i < len(words) - 1 else "")
            if len(buffer) > 20 or i == len(words) - 1:
                await record_event(run_id, "token", buffer)
                buffer = ""
    await record_event(run_id, "citations", turn.citations)
    await record_event(run_id, "agent_steps", turn.agent_steps)
    if turn.routing:
        await record_event(run_id, "routing", turn.routing)
    if turn.council_run_id:
        await record_event(run_id, "council_run_id", turn.council_run_id)
    # Everything above is the answer; this tells the client it is complete and what produced
    # it, before scoring starts.
    await record_event(run_id, "answer", turn.summary())


async def run_chat_turn_tracked(
    run_id: str,
    query: str,
    document_id: str | None,
    strategy: str,
    reveal_pii: bool,
    session_id: str,
    detail: str | None = None,
) -> None:
    """The background task behind POST /chat. Keeps the persisted ChatRun updated while the
    work happens (via a concurrent relay of real stage transitions — see app/agents/runs.py),
    streams the answer as soon as it exists, then scores it and saves the report."""
    settings = get_settings()
    stop_relay = asyncio.Event()
    relay_task = asyncio.ensure_future(relay_trace_to_run(run_id, session_id, stop_relay))

    live = _LiveTokens(run_id)

    async def attempt_once(*, force_fast: bool, timeout: float) -> Turn:
        reset_llm_call_budget(settings.max_llm_calls_per_run)
        llm_client.set_token_sink(live)
        try:
            # Scoring, enrichment and evaluation jobs hold their model calls while this runs.
            async with llm_client.interactive():
                return await asyncio.wait_for(
                    produce_turn(
                        query,
                        document_id,
                        strategy,
                        reveal_pii=reveal_pii,
                        session_id=session_id,
                        detail=detail,
                        force_fast=force_fast,
                    ),
                    timeout=timeout,
                )
        finally:
            llm_client.set_token_sink(None)
            clear_llm_call_budget()

    attempt = 1
    try:
        try:
            turn = await attempt_once(force_fast=False, timeout=settings.run_timeout_seconds)
        except (TimeoutError, LlmBudgetExceededError) as first_exc:
            logger.warning(
                "Chat run %s: attempt 1 failed (%s) — retrying once with the fast model",
                run_id,
                type(first_exc).__name__,
            )
            await record_event(
                run_id,
                "stage",
                {
                    "stage": "retry",
                    "status": "generating",
                    "note": "First attempt timed out — retrying with a faster model.",
                },
            )
            await set_run_status(run_id, "generating", stage="retry", attempt=2)
            attempt = 2
            turn = await attempt_once(force_fast=True, timeout=settings.run_retry_timeout_seconds)
    except (TimeoutError, LlmBudgetExceededError) as exc:
        stop_relay.set()
        await relay_task
        message = (
            "This question took too long to answer even with the faster retry — try a more "
            "specific question, or try again."
            if isinstance(exc, TimeoutError)
            else (
                "This question required more model calls than the per-run budget allows — try "
                "a more specific question."
            )
        )
        await record_event(run_id, "error", {"code": "run_timeout", "message": message})
        await set_run_status(run_id, "failed", error=message, attempt=2)
        return
    except (UnknownStrategyError, IndexMismatchError) as exc:
        stop_relay.set()
        await relay_task
        code = "index_mismatch" if isinstance(exc, IndexMismatchError) else "invalid_strategy"
        await record_event(run_id, "error", {"code": code, "message": str(exc)})
        await set_run_status(run_id, "failed", error=str(exc))
        return
    except asyncio.CancelledError:
        # A user cancel (POST /runs/{id}/cancel) lands here: record a visible terminal state
        # before letting it propagate.
        stop_relay.set()
        relay_task.cancel()
        await record_event(run_id, "error", {"code": "cancelled", "message": "Cancelled."})
        await set_run_status(run_id, "cancelled", error="Cancelled by user.")
        raise
    except Exception as exc:  # noqa: BLE001 — a run failing must surface as a clear status
        stop_relay.set()
        await relay_task
        logger.exception("Chat run %s failed", run_id)
        message = f"Something went wrong while answering: {exc}"[:500]
        await record_event(run_id, "error", {"code": "run_failed", "message": message})
        await set_run_status(run_id, "failed", error=message)
        return

    stop_relay.set()
    await relay_task

    # The answer goes out now. Nothing after this point can change it or trigger a retry.
    await _emit_answer(run_id, turn, live)
    await set_run_status(run_id, "verifying", stage="scoring")
    llm_client.mark_background()  # scoring never makes the next question wait

    try:
        report_id, quality = await finalize_turn(turn, attempt=attempt)
    except Exception as exc:  # noqa: BLE001 — the answer was delivered; report the gap honestly
        logger.exception("Chat run %s: saving the report failed", run_id)
        message = f"The answer was delivered, but its report could not be saved: {exc}"[:500]
        await record_event(run_id, "error", {"code": "report_failed", "message": message})
        await set_run_status(run_id, "failed", error=message, attempt=attempt)
        return

    await record_event(run_id, "quality", quality)
    await record_event(run_id, "done", {"report_id": report_id, "cache_hit": turn.cache_hit})
    await set_run_status(run_id, turn.outcome, report_id=report_id, attempt=attempt)
