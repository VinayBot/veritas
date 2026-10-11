"""Summarizer: the route for broad, document-wide questions ("history of X", "tell me about
X") that the Planner classifies as "summary" instead of "factoid"/"multi_hop" (see
planner.py:route_after_planner).

These questions were previously forced through the same rewriter<->critic corrective-RAG loop
as a narrow factoid lookup: retrieve top-k by query similarity, judge "is this enough evidence
to answer", and if not, rewrite and retry up to 3 times. That loop is the wrong tool for a
broad question — "insufficient evidence" isn't really the failure mode, "the top-5 most
query-similar chunks aren't a representative sample of the whole document" is — so retrying
with a reformulated query mostly re-ran the same expensive loop against the same narrow slice
without ever addressing the actual gap. See docs/DECISIONS.md's Fix 1 entry for the live
evidence this is based on.

This node instead: (1) retrieves a wider candidate set and re-selects it for *diversity* across
the document via MMR (`app.retrieval.dedupe.mmr_select`, already used elsewhere for context
dedup — reused here for the opposite purpose, spreading selection out rather than narrowing it);
(2) summarizes small batches of that diverse set independently (map); (3) combines those partial
notes into one final, cited answer against the full numbered context (reduce).

force_fast (the post-timeout retry — see docs/DECISIONS.md and orchestrator.py): a live timed
run against this project's own 16GB-tier hardware measured ~15-30s per real local-model call
here, so the full map-reduce chain (2-3 map calls + 1 reduce call, the reduce call on the
stronger council model) can genuinely take over a minute on its own — on force_fast this skips
the map step entirely (one direct call over a smaller top-k, not batched-then-combined) and
uses the fast default model throughout instead of escalating to the stronger one, so the retry
is actually cheaper than the attempt that just timed out, not a second shot at the same cost.
"""

from __future__ import annotations

import re

from app.agents.context_utils import build_numbered_context
from app.agents.state import AgentState, Citation, record_step
from app.core.config import get_settings
from app.core.tracing import trace_bus
from app.guardrails.retrieval import scan_hits
from app.llm.client import LlmUnavailableError, complete
from app.retrieval import service as retrieval_service

_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")

_WIDE_K = 8
_FAST_K = 5
_BATCH_SIZE = 4

_BATCH_SUMMARY_PROMPT = (
    "Question: {query}\n\nSummarize what these excerpts say that's relevant to the question, "
    "in 2-4 sentences. Don't invent anything not stated in the excerpts.\n\n{context}\n\n"
    "Summary:"
)
_COMBINE_PROMPT = (
    "Question: {query}\n\nWhile reading different parts of a document, you took these partial "
    "notes:\n{notes}\n\nNow write one complete, well-organized answer to the question using "
    "ONLY the numbered source excerpts below (the notes above may be incomplete — treat the "
    "excerpts as the real evidence) — cite inline using [1], [2], etc. matching the numbers "
    "below.\n\n{context}\n\nFinal answer:"
)


async def summarizer_node(state: AgentState) -> dict:
    query = state["query"]
    doc_id = state.get("document_id")
    force_fast = state.get("force_fast", False)
    settings = get_settings()

    async with trace_bus.stage(
        state["session_id"], "summarizer", from_stage="planner", to_stage="verifier"
    ) as h:
        fused_hits = await retrieval_service.search(
            query,
            k=_FAST_K if force_fast else _WIDE_K,
            doc_id=doc_id,
            mode="hybrid",
            rerank=True,
            dedupe_strategy="mmr",
        )
        hits: list[dict] = [
            {"chunk_id": fh.chunk_id, "text": fh.text, "score": fh.score, "source": "hybrid"}
            for fh in fused_hits
        ]
        hits = await scan_hits(hits, state["session_id"], h.trace_id)
        h.set_metric("hit_count", len(hits))

        if not hits:
            h.set_output("No evidence retrieved for a document-wide summary.")
            return {
                "answer": "I don't have enough information in this document to answer that.",
                "citations": [],
                "retrieved": [],
                "agent_steps": record_step(
                    state, "summarizer", "No evidence found for a broad/summary question."
                ),
            }

        notes: list[str] = []
        if not force_fast:
            for i in range(0, len(hits), _BATCH_SIZE):
                batch = hits[i : i + _BATCH_SIZE]
                batch_context = "\n---\n".join(hit["text"] for hit in batch)
                try:
                    note = await complete(
                        _BATCH_SUMMARY_PROMPT.format(query=query, context=batch_context),
                        max_tokens=150,
                        temperature=0.2,
                    )
                except LlmUnavailableError:
                    note = ""
                if note.strip():
                    notes.append(note.strip())

        full_context = build_numbered_context(hits)
        combine_model = (
            settings.default_llm_model
            if force_fast
            else (settings.council_model_list[0] if settings.council_model_list else None)
        )
        try:
            answer = await complete(
                _COMBINE_PROMPT.format(
                    query=query,
                    notes="\n".join(f"- {n}" for n in notes) or "(none)",
                    context=full_context,
                ),
                model=combine_model,
                max_tokens=600,
                temperature=0.2,
            )
        except LlmUnavailableError:
            answer = (
                "I'm unable to generate an answer right now — the language model is unavailable."
            )

        h.set_metric("batch_count", len(notes))
        h.set_metric("force_fast", force_fast)
        h.set_output(answer[:200])

    cited_markers = {int(m) for m in _CITATION_MARKER_RE.findall(answer)}
    citations: list[Citation] = [
        Citation(marker=i + 1, chunk_id=hit["chunk_id"], text=hit["text"][:300])
        for i, hit in enumerate(hits)
        if (i + 1) in cited_markers
    ]

    summary = f"Summarized across {len(hits)} diverse excerpt(s) via {len(notes)} partial note(s)."
    return {
        "answer": answer,
        "citations": citations,
        "retrieved": hits,
        "agent_steps": record_step(state, "summarizer", summary),
    }
