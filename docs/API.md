# API

Full OpenAPI schema is auto-generated at `/docs` for whatever currently exists. This file is
updated as each phase lands — examples below are copied from real responses, not written by
hand.

| Method | Path | Purpose | Status |
|---|---|---|---|
| GET | `/api/v1/health` | Liveness + real Ollama/model status | ✅ |
| POST | `/api/v1/documents/upload` | Multipart upload; parses, refines, PII-tokenizes | ✅ |
| POST | `/api/v1/documents/url` | Scrape a public URL (SSRF-guarded) and ingest it | ✅ |
| GET | `/api/v1/documents/{id}` | Metadata, refinement report, PII summary | ✅ |
| GET | `/api/v1/documents/{id}/profile` | Real-computed document profile features | ✅ |
| POST | `/api/v1/documents/{id}/advisor/run` | Force a tournament + advisor recommendation now | ✅ |
| GET | `/api/v1/documents/{id}/advisor` | Latest persisted recommendation | ✅ |
| POST | `/api/v1/documents/{id}/advisor/decision` | `accept` (real re-index) / `ignore` | ✅ |
| POST | `/api/v1/pii/reveal` | Audited de-tokenization | ✅ |
| POST | `/api/v1/retrieval/search` | Hybrid/dense/BM25 search (not in the original contract — see below) | ✅ |
| POST | `/api/v1/chat` | SSE chat stream (agentic/hybrid/graph) + quality + routing/council | ✅ |
| GET | `/api/v1/reports/{report_id}` | Per-answer report with real Estimated quality metrics | ✅ |
| GET | `/api/v1/council/{run_id}` | Full LLM Council transcript for one chat turn | ✅ |
| POST | `/api/v1/documents/{id}/eval/datasets/generate` | Synthetic eval dataset from real chunks | ✅ |
| POST | `/api/v1/eval/benchmarks/run` | Multi-config benchmark against a synthetic dataset | ✅ |
| GET | `/api/v1/eval/benchmarks/{id}` | Fetch a persisted benchmark run | ✅ |
| GET | `/api/v1/graph/{document_id}` | Graph nodes/edges, optional `?query=` traversal | ✅ |
| GET | `/api/v1/audit` | Guardrail decision audit log | ✅ |
| POST | `/api/v1/redteam/run` | Attack suite (>=40 attacks + a benign set, real block/false-positive rates) | ✅ |
| WS | `/ws/trace/{session_id}` | Live trace events, replayed from history for late subscribers | ✅ |

Every response error uses the envelope `{code, message, trace_id}` (`app/core/errors.py`).

## POST /api/v1/documents/upload

```
curl -X POST http://localhost:8000/api/v1/documents/upload -F "file=@handbook.docx"
```
```json
{"document_id": "187d2aed-5d3d-4b46-9382-d6cb9b270e57", "job_id": "187d2aed-5d3d-4b46-9382-d6cb9b270e57"}
```

`job_id == document_id` for now — ingestion runs synchronously within the request (see
[DECISIONS.md](DECISIONS.md)). Supported extensions: `.pdf .docx .pptx .png .jpg .jpeg .tiff`
(Docling), `.html .htm` (trafilatura), `.md .txt .csv`, `.eml` (stdlib), `.rtf` (striprtf),
`.doc .xls` (LibreOffice, if installed — otherwise a clear `unsupported_format` error).

## POST /api/v1/documents/url

```json
{"url": "https://example.com/", "depth": 0}
```

Only `http`/`https`; blocks localhost/private/link-local/reserved addresses (re-checked on every
redirect hop); respects `robots.txt`; 10s timeout; 5MB cap; optional same-domain crawl up to
`SCRAPE_MAX_CRAWL_DEPTH`/`SCRAPE_MAX_PAGES`. Returns `scrape_blocked` (422) if the SSRF guard or
robots.txt rejects the URL.

## GET /api/v1/documents/{id}

```json
{
  "id": "187d2aed-5d3d-4b46-9382-d6cb9b270e57",
  "filename": "test_handbook.docx",
  "source_type": "upload",
  "status": "ready",
  "quality_score_before": 95.0,
  "quality_score_after": 100.0,
  "fix_log": [],
  "language": "en",
  "pii_counts": {"PERSON": 2, "EMAIL_ADDRESS": 1, "DATE_TIME": 4}
}
```
(trimmed — real field list is in `app/api/schemas/documents.py`.) `pii_counts` is by Presidio
entity type; values are masked everywhere except through an explicit, audited `/pii/reveal` call.

## GET /api/v1/documents/{id}/profile

Recomputed live from `Document.masked_text` on every call (cheap enough — no caching, so it's
never stale). Real response, captured from a 7-section/9.3KB handbook upload:

```json
{
  "document_id": "c4e8fc97-...", "pages_estimated": 1, "tokens": 558, "language": "en",
  "heading_density": 0.263, "table_ratio": 0.0, "list_ratio": 0.0, "code_ratio": 0.0,
  "avg_sentence_length": 18.4, "avg_paragraph_length": 46.0, "duplication_ratio": 0.0,
  "ocr_confidence": null, "entity_density": 43.0, "relation_density": 0.0,
  "document_type": "mixed"
}
```

`422 document_not_ready` if `masked_text` isn't populated yet (ingestion failed or is still
running — ingestion is synchronous today, so this is effectively unreachable via the HTTP API,
but the service layer guards it rather than assuming).

## Advisor: `POST .../advisor/run`, `GET .../advisor`, `POST .../advisor/decision`

A real 5-candidate tournament (`app/profiler/tournament.py`) against a freshly-generated
synthetic eval set, scored with the real retrieval-metrics module and the real LLM judge —
never a lookup table. Runs automatically once per ingested document (two new ingestion trace
stages, `profile` then `advisor`) whenever the document has at least
`MIN_CHUNKS_FOR_TOURNAMENT = 3` baseline chunks; `POST .../advisor/run` forces a fresh run on
demand (same threshold applies — `422 advisor_unavailable` below it, or if the LLM is
unavailable so no synthetic questions could be generated).

Real response, same handbook as above (`POST /documents/{id}/advisor/run`):

```json
{
  "document_id": "c4e8fc97-...",
  "baseline": {"name": "baseline", "chunking_strategy": "recursive", "chunking_kwargs": {"size": 512, "overlap": 64}, "rerank": false, "llm_model": null, "retrieval_metrics": {"precision_at_5": 0.5, "recall_at_5": 1.0, "ndcg_at_5": 0.969, "n": 4.0}, "faithfulness": 0.70, "avg_latency_ms": 19.8, "index_size": 4, "composite_score": 0.912},
  "suggested": {"name": "recursive_256", "chunking_strategy": "recursive", "chunking_kwargs": {"size": 256, "overlap": 32}, "rerank": false, "llm_model": null, "retrieval_metrics": {"precision_at_5": 0.95, "recall_at_5": 1.0, "ndcg_at_5": 1.0, "n": 4.0}, "faithfulness": 0.75, "avg_latency_ms": 17.3, "index_size": 10, "composite_score": 0.936},
  "gain_ndcg_points": 3.07,
  "rationale": [
    "recursive_256 scored +3.1 nDCG@5 points over the baseline across 4 synthetic questions actually run against both configurations.",
    "Smaller chunks (256 tokens vs. 512) produced 10 chunks (baseline: 4) and scored higher recall — this document's answers tend to be short, specific facts rather than long passages."
  ],
  "suggested_mode": "agentic",
  "mode_reason": "No single strong structural signal (graph-dense or FAQ-simple) was measured, so the general-purpose agentic pipeline — which can decompose multi-hop or comparison questions on its own — is the safer default.",
  "decision": null
}
```

`GET .../advisor` returns the same shape from the latest persisted recommendation (`404
no_recommendation` if none exists yet). `POST .../advisor/decision {"decision": "accept" |
"ignore"}`:

- **`ignore`** just records the decision — the index is untouched.
- **`accept`** is a real re-chunk/re-embed/re-index with the suggested candidate's chunking
  config: deletes the current chunk rows, vectors, and the graph edges tagged with this
  document (`GraphStore.remove_doc_edges`, entity nodes are kept), then re-indexes from
  `Document.masked_text` with the new chunker and re-runs GraphRAG extraction. Live-verified on
  the handbook above: `chunk_count` went `4 -> 10` and `GET /documents/{id}` reflects it
  immediately; chat and `GET /graph/{id}` both kept working against the re-indexed document
  right after. Both configurations are **not** kept side by side for a live toggle — accept
  commits to the suggested config (see docs/DECISIONS.md's Phase 8 entry for the scope line).

## POST /api/v1/pii/reveal

```json
{"tokens": ["<EMAIL_ADDRESS_a0f4ff>"], "session_id": "my-session"}
```
```json
{"revealed": {"<EMAIL_ADDRESS_a0f4ff>": "jane.smith@example.com"}, "not_found": []}
```

Every call is written to the `PiiRevealEvent` audit trail — there is no silent reveal path.

## POST /api/v1/retrieval/search

Not in the brief's Section 13 contract — added so Phase 3's hybrid search is actually
exercisable as a running API (and because Phase 6's agentic `hybrid_search` tool is this exact
call).

```json
{"query": "how much does the Pro plan cost", "document_id": "d65a77f4-...", "mode": "hybrid", "k": 3}
```
```json
{
  "hits": [
    {
      "chunk_id": "9a427769-799d-44e0-99f5-e235f4d26bff",
      "score": 0.0164,
      "text": "# Pricing\n\nThe Pro plan costs 49 dollars per month...",
      "dense_rank": 1, "bm25_rank": 1, "dense_score": 0.906, "bm25_score": 0.621
    }
  ]
}
```

`mode` is `hybrid` (Reciprocal Rank Fusion, default), `dense`, or `bm25`. Omit `document_id` to
search across every ingested document. Verified live with two different real documents: an
unscoped query ranks the better match from either one; a `document_id`-scoped query returns only
that document's chunks even when the other document would otherwise have scored higher.

Phase 4 added the rest of Section 8.A's Hybrid RAG pipeline as request flags, each off by
default so Phase 3 behavior is unchanged unless opted into:

| Field | Default | Effect |
|---|---|---|
| `use_hyde` | `false` | Rewrites the query into a hypothetical answer passage before embedding (falls back to the raw query if the LLM is unavailable) |
| `rerank` | `false` | Cross-encoder (`RERANKER_MODEL`) rescoring of the fused candidates against the *original* query |
| `dedupe_strategy` | `null` | `"mmr"`, `"cosine"`, or `"ngram"` — see `app/retrieval/dedupe.py` |
| `compress` | `false` | Extractive sentence-level compression of each hit down to `max_context_tokens` total |
| `max_context_tokens` | `1000` | Token budget `compress` divides across the returned hits |

Stage order is fixed: HyDE rewrite -> hybrid/dense/BM25 fetch -> RRF fuse -> rerank -> dedupe ->
truncate to `k` -> compress.

## GET /api/v1/graph/{document_id}

Built at ingestion time (spaCy NER + LLM triple extraction + entity resolution + Louvain
communities — Section 8.B), scoped by `doc_id`. Add `?query=...&hops=2` to instead return the
traversal path from entities linked to that query.

```json
{
  "nodes": [
    {"id": "a1b2...", "label": "ORG", "name": "Silverpine Logistics", "doc_ids": ["..."], "mentions": ["Silverpine Logistics"], "community": 0}
  ],
  "edges": [
    {"source": "a1b2...", "target": "c3d4...", "predicate": "signed_contract_with", "doc_id": "...", "chunk_id": "..."}
  ],
  "linked_entities": null
}
```

**Important interaction with the PII vault:** PII masking runs before graph extraction (Section
6.3 requires raw PII never reach the graph), so any entity Presidio flags — most prominently
`PERSON` names — appears as an opaque `<TYPE_hex>` token rather than its real name unless masking
is narrow enough to leave it untouched (see docs/DECISIONS.md's Phase 5 entry for the full
finding and the detector fix that resulted from it). Organizations/locations are not masked by
default; people are.

## POST /api/v1/chat

Primary mode is `agentic` (the full LangGraph state machine — planner, rewriter, retriever,
critic, synthesizer, verifier, guardian; see `app/agents/graph.py`); `hybrid` and `graph` are
simpler, cheaper direct pipelines (one retrieval tool, one synthesis call, still guardrail-
wrapped) the user can select instead.

```json
{"message": "How much vacation do employees get?", "document_id": "...", "mode": "agentic", "reveal_pii": false}
```

Response is `text/event-stream`. Events, in order: `session` (`{session_id, cache_hit}`),
one or more `token` (the final, already-verified answer chunked for a responsive typing feel —
see docs/DECISIONS.md on why nothing streams before verification completes), `citations`
(`[{marker, chunk_id, text}]`), `agent_steps` (`[{node, summary}]` — the short, human-readable
trace the Workspace UI's agent timeline will render), `quality` (see below), `routing` (only
when `council` was false), `council_run_id` (only when `council` was true), then `done`
(`{report_id, cache_hit}`). An invalid `mode` yields a single `error` event rather than an HTTP
error status (SSE streams always return 200 once started).

**`quality`** — real LLM-judge scoring of the actual answer just generated, not a placeholder.
Live-captured example (hybrid mode, one citation):

```json
{"label": "estimated", "faithfulness": 0.8, "relevancy": 0.8, "citation_validity": 1.0, "confidence": 0.8667}
```

Always labelled `"estimated"` — a live chat turn has no ground-truth answer to verify against
(that only exists in the benchmark runner's synthetic eval set, where the same scoring
functions produce "Verified" numbers instead; see `app/evaluation/judge.py` and
docs/DECISIONS.md). `faithfulness` is `null` when there were no citations to be faithful to.

**`routing`** (`council: false`, the default) — which model actually answered, from the real
per-query Model Router (`app/llm/router.py`). Live-captured, a short factoid question:

```json
{"primary_model": "ollama/llama3.2:3b", "model_used": "ollama/llama3.2:3b", "fell_back": false, "latency_ms": 1270.4}
```

Longer or comparison-phrased questions route to the strongest locally-available model instead
of the fast default; if that model doesn't answer within `MODEL_ROUTER_LATENCY_BUDGET_MS`
(12,000 ms default), this falls back to the fast default so the turn doesn't hang. Live-caught,
unprompted, under real concurrent load from this project's own test suite running at the same
time:

```json
{"primary_model": "ollama/qwen2.5:7b-instruct", "model_used": "ollama/llama3.2:3b", "fell_back": true, "latency_ms": 23491.1}
```

**`council`** (request field) — opt in to real multi-model council synthesis instead of the
Model Router's single model: every model in `COUNCIL_MODELS` answers independently, each
anonymously peer-reviews every answer, and `CHAIRMAN_MODEL` synthesizes the final answer. When
`council: true`, the `done` event's `report_id` links to a `council_run_id` carrying the full
transcript — see `GET /api/v1/council/{run_id}` below. `routing` is omitted on these turns
(the council, not the router, decided which models ran).

## GET /api/v1/reports/{report_id}

```json
{
  "id": "...", "session_id": "...", "document_id": "...", "mode": "hybrid",
  "query": "How many vacation days do employees accrue per month?",
  "answer": "According to the context, employees accrue two paid vacation days for every month of continuous service... [1]",
  "citations": [{"marker": 1, "chunk_id": "...", "text": "# Vacation Policy\n\nEmployees accrue two paid vacation days..."}],
  "agent_steps": [{"node": "retriever", "summary": "Hybrid retrieval found 5 piece(s) of evidence."}],
  "cache_hit": false,
  "quality": {"label": "estimated", "faithfulness": 0.8, "relevancy": 0.8, "citation_validity": 1.0, "confidence": 0.8667},
  "routing": {"primary_model": "ollama/llama3.2:3b", "model_used": "ollama/llama3.2:3b", "fell_back": false, "latency_ms": 1270.4},
  "council_run_id": null
}
```

`quality` and `routing` are the same objects their SSE events carry — persisted so a past
turn's report still shows them. Exactly one of `routing` / `council_run_id` is non-null,
matching whichever the request's `council` flag selected.

## GET /api/v1/council/{run_id}

The full transcript behind one council-mode chat turn — every member's raw answer and
latency, every reviewer's per-answer scores, the computed agreement score, and the chairman's
final synthesis. This is what the Model Selection Arena UI (Phase 11) renders; the chat
response itself only carries the final answer and this run's id.

```json
{
  "id": "...", "session_id": "...", "query": "How much vacation do employees get?",
  "members": ["ollama/qwen2.5:7b-instruct", "ollama/gemma2:2b"],
  "chairman_model": "ollama/llama3.2:3b",
  "member_answers": [
    {"model": "ollama/qwen2.5:7b-instruct", "label": "A", "answer": "...", "latency_ms": 4821.3},
    {"model": "ollama/gemma2:2b", "label": "B", "answer": "...", "latency_ms": 1902.7}
  ],
  "peer_reviews": [
    {"reviewer_model": "ollama/qwen2.5:7b-instruct", "scores": {"A": 9.0, "B": 7.0}},
    {"reviewer_model": "ollama/gemma2:2b", "scores": {"A": 8.0, "B": 6.0}}
  ],
  "agreement_score": 0.9,
  "final_answer": "..."
}
```

`404 council_run_not_found` for an unknown id. See docs/DECISIONS.md for exactly how
`agreement_score` is computed and why it's excluded (not defaulted) when a label got fewer
than two real reviewer scores.

## POST /api/v1/documents/{id}/eval/datasets/generate

Generates a real synthetic eval set from the document's actual persisted chunks (factoid,
multi-hop, comparison, unanswerable, and — if any chunks have masked PII tokens — pii
categories; see `app/evaluation/datasets.py`) and persists it as a new version. `422
dataset_empty` if the document has no indexed chunks yet or the LLM is unavailable.

```json
{"target_size": 10}
```
```json
{"dataset_id": "35b07a6d-...", "document_id": "c4e8fc97-...", "version": 1, "item_count": 7, "categories": {"factoid": 2, "comparison": 2, "unanswerable": 2, "pii": 1}}
```

`item_count` is usually below `target_size`: generation can fail per-item (LLM returned
unparseable JSON) and a final embedding-similarity dedupe step drops near-duplicate questions —
both real, not padded back up to the requested count.

## POST /api/v1/eval/benchmarks/run, GET /api/v1/eval/benchmarks/{id}

Runs real configs (`bm25`, `dense`, `hybrid`, `hybrid_rerank_hyde`, `graph`, `agentic`) against
a freshly-generated synthetic dataset, scores each with the real retrieval-metrics module and
LLM judge, runs the real red-team suite for the safety signal, and scans every indexed chunk
for raw PII — same engine `make eval`/`docs/BENCHMARKS.md` use, which this call also refreshes.

```json
{"document_id": "c4e8fc97-...", "configs": ["bm25", "hybrid"], "dataset_target_size": 5}
```

Real response from the live run above (same document, after the `accept` re-index to
`recursive_256`):

```json
{
  "id": "e8886803-...", "document_id": "c4e8fc97-...",
  "config_results": [
    {"name": "bm25", "retrieval_metrics": {"precision_at_5": 0.2, "recall_at_5": 0.875, "ndcg_at_5": 0.903, "n": 4.0}, "faithfulness": 0.8, "correctness": 0.7, "citation_validity": 1.0, "p50_latency_ms": 1.7, "p95_latency_ms": 4.8, "n_samples": 4, "production_score": 0.590, "passes_hard_gates": false},
    {"name": "hybrid", "retrieval_metrics": {"precision_at_5": 0.2, "recall_at_5": 0.875, "ndcg_at_5": 0.75, "n": 4.0}, "faithfulness": 0.8, "correctness": 0.5, "citation_validity": 1.0, "p50_latency_ms": 196.2, "p95_latency_ms": 247.7, "n_samples": 4, "production_score": 0.516, "passes_hard_gates": false}
  ],
  "injection_block_rate": 0.976, "pii_leak_count": 1, "recommended_config": "bm25"
}
```

`pii_leak_count: 1` here is real and left unedited rather than re-run until it looked cleaner —
see docs/DECISIONS.md's Phase 8 entry for what it actually was (a chunk-boundary NER false
positive on a markdown heading, not a real PII disclosure) and why both configs correctly
failed `passes_hard_gates` as a result. `recommended_config` picks the highest production score
among configs that pass the hard gates, or — as here, when none do — the highest score
overall, so there's always an answer to "what would ship today," not a null.

`GET /eval/benchmarks/{id}` returns this same shape from the persisted row (`404
benchmark_not_found` otherwise).

## GET /api/v1/audit

```
GET /api/v1/audit?session_id=...&layer=input&limit=50
```

Every guardrail decision, on every layer (`input` | `retrieval` | `output`) — allow decisions
are logged too, not just blocks. `layer` and `session_id` are optional filters.

```json
{
  "entries": [
    {
      "id": 42, "trace_id": "...", "session_id": "...", "layer": "input",
      "rule": "prompt_injection", "score": 0.95, "decision": "block",
      "redacted_excerpt": "Ignore all previous instructions...",
      "created_at": "2026-10-09T22:48:24Z"
    }
  ]
}
```

## POST /api/v1/redteam/run

Runs the real red-team corpus (`app/guardrails/redteam/attacks.py` — 42 attacks across 5
categories, 15 benign) through the live input guardrail and returns real, computed aggregates
— nothing here is a lookup table. Same thing `make redteam` runs.

```json
{
  "total_attacks": 42, "blocked_attacks": 41, "block_rate": 0.976,
  "total_benign": 15, "false_positives": 1, "false_positive_rate": 0.067,
  "by_category": {
    "direct_injection": {"total": 10, "blocked": 10, "block_rate": 1.0},
    "jailbreak": {"total": 10, "blocked": 9, "block_rate": 0.9}
  }
}
```

Hard gates (Section 11 and docs/DECISIONS.md): block rate >= 95%, false-positive rate <= 10%.
Real numbers from the last local run (Ollama/Llama Guard available) are above; CI runs the
same suite without Ollama installed (Llama Guard calls fail open to "safe," so CI exercises the
regex + DeBERTa layers) and still clears both gates — verified at 95.2%/6.7%.

## WS /ws/trace/{session_id}

The Architecture tab's only source of animation (`app/api/routes/trace.py`) — a thin
pass-through onto the real `trace_bus` every pipeline stage already publishes to
(`app/core/tracing.py`); nothing here is synthesized or timer-driven. `session_id` is the
chat session id for chat turns, or the `document_id` for ingestion (ingestion uses the
document's own id as its trace session — see `app/ingestion/service.py`).

On connect, every historical `TraceEvent` for that session is replayed first (so a client that
connects after a pipeline already finished — the common case today, since ingestion runs
synchronously within the HTTP request — still sees every stage that ran), then new events
stream as they're published. Each frame is one JSON-encoded `TraceEvent`:

```json
{"trace_id": "...", "session_id": "...", "stage": "chunk", "status": "done", "started_at": "2026-10-10T...", "duration_ms": 42.1, "from_stage": "pii_vault", "to_stage": "embed", "output_preview": "6 chunks", "metrics": {"chunk_count": 6, "strategy": "recursive"}}
```

`status` is one of `queued | running | done | blocked | error`. Connecting to a session with
no history yet (or ever) is not an error — the socket just stays open with nothing to replay.
