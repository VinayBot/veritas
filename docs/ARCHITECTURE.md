# Architecture

What's actually built, by data flow — not a plan, a description of the current tree. See
[docs/API.md](API.md) for the exact request/response contracts and [docs/DECISIONS.md](DECISIONS.md)
for why things are shaped this way.

## Ingestion flow

```
upload/URL -> parse -> refine -> pii_vault -> chunk -> embed -> index -> graph -> profile -> advisor
```

Every arrow above is a real `trace_bus` stage (`app/core/tracing.py`), published as a
`TraceEvent` and streamed live over `WS /ws/trace/{document_id}` — this is what the frontend's
Ingestion Theater (`frontend/src/pages/workspace-page.tsx`) animates from, not a timer.

- **Parse** (`app/ingestion/`): format-specific parsers behind one registry — Docling for
  PDF/DOCX/PPTX/images, trafilatura for HTML, stdlib/`striprtf`/`email` for the rest. URL
  ingestion goes through an SSRF-guarded scraper first (`app/ingestion/scraper.py`).
- **Refine** (`app/ingestion/refiner.py`): deterministic text-quality repair (whitespace,
  encoding artifacts, OCR noise), with a before/after quality score.
- **PII vault** (`app/privacy/`): Presidio detection -> deterministic HMAC-SHA256 tokenization
  -> Fernet-encrypted vault. Everything after this stage only ever sees `<TYPE_hex>` tokens;
  raw PII is reconstructed only through the audited `/pii/reveal` endpoint.
- **Chunk/Embed/Index** (`app/chunking/`, `app/embeddings/`, `app/retrieval/indexing.py`): one
  path (`index_document()`) that chunks, embeds, and writes to both the dense (Chroma) and
  sparse (BM25) stores together, so they can't drift out of sync. Six chunking strategies are
  registered (`app/chunking/registry.py`); the baseline is `recursive(512, 64)`.
- **Graph** (`app/graphrag/`): spaCy NER + LLM JSON-schema triple extraction on each chunk,
  deterministic entity resolution, written into a `GraphStore` (NetworkX by default, a Neo4j
  adapter behind the same `Protocol` for the `neo4j` Compose profile).
- **Profile/Advisor** (`app/profiler/`): real document-feature extraction, then (above
  `MIN_CHUNKS_FOR_TOURNAMENT`) a real 5-candidate chunking tournament against a synthetic eval
  set generated from the document's own chunks — the result backs the Dashboard's
  Baseline-vs-Suggested comparison and its real Accept (re-index) / Ignore decision.

## Chat flow

`app/agents/orchestrator.py::run_chat_turn` is the single entry point for all three modes:

- **`agentic`** (default): a LangGraph state machine (`app/agents/graph.py`) —
  `guardian_in -> planner -> rewriter -> retriever -> critic -> synthesizer -> verifier ->
  guardian_out`, with bounded retry loops (critic can send back to the rewriter;
  the verifier can send back to the synthesizer once).
- **`hybrid` / `graph`**: simpler, cheaper direct pipelines (one retrieval call, one synthesis
  call), still guardrail-wrapped on both ends.
- **Council** (opt-in, `council: true`): replaces the single synthesis call in *either* path
  above with `app/council/service.py::run_council` — independent member answers, anonymized
  peer review, chairman synthesis, a real agreement score.
- **Model Router** (the default, non-council path): `app/llm/router.py` picks a model based on
  real query-complexity signals and falls back to the fast default model on a real latency
  budget timeout.
- A semantic cache (`app/retrieval/semantic_cache.py`) can short-circuit the whole thing for a
  near-identical repeat question — the output guardrail still re-runs unconditionally even on
  a cache hit.

Every turn ends in a persisted `ChatReport` (`app/agents/models.py`) carrying the answer,
citations, a real LLM-judged "Estimated" quality report, and (depending on mode) either
`routing` or `council_run_id` metadata.

## Guardrail flow

Three layers, every decision logged (`app/guardrails/audit.py`), not just blocks:

```
input:  regex heuristics -> prompt-injection classifier (DeBERTa) -> Llama Guard
output: secret-leak regex -> PII redaction -> Llama Guard -> mandatory-citations check
```

`app/guardrails/redteam/` runs a 42-attack/15-benign corpus against the live input guardrail
and gates on block rate (>=95%) and false-positive rate (<=10%) — `make redteam` / `POST
/redteam/run`.

## Frontend

`frontend/src/pages/` — three tabs and a landing page. **Workspace** (upload, streamed chat,
strategy and model pickers, recommendation, per-answer analysis), **Architecture** (xyflow
diagram generated from `GET /architecture/graph`, driven by the trace WebSocket) and
**Evaluation** (`components/evaluation/`: Usage with measured quality, Knowledge graph, Safety;
charts are ECharts through `components/charts/EChart.tsx`, which reads its colours from the
design tokens). Design tokens live in `src/styles/tokens.css`. `frontend/src/lib/api/`
is the one typed client every page goes through; `frontend/src/hooks/useTraceEvents.ts` is the
one WebSocket subscription both the Workspace and Architecture pages reuse.


## Request path for a question

`POST /chat` → `agents/orchestrator.run_chat_turn_tracked` → the chosen strategy from
`rag_engines/registry.py` (`rag_engines/execute.retrieve` for the direct strategies, the
LangGraph agent for `agentic`, `council/` for `council`) → `llm/router` → Ollama. Tokens are
relayed to the client as they are written; the output guardrail, `tidy_answer` and then
scoring follow. Scoring, graph extraction and background jobs yield the model to any question
in progress (`llm/client.interactive`). `GET /architecture/graph` describes all of this from
the code itself: packages are discovered, agent nodes are read off the compiled graph, and
each declared edge is checked against real imports by `tests/test_architecture_api.py`.
