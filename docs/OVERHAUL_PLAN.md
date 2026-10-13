# Overhaul plan — UI, Architecture & Multi-RAG

Phase 0 output for the "Veritas — UI, Architecture & Multi-RAG Overhaul" brief. Written on
2026-10-13 against branch `feat/ui-arch-eval-kg` at `f7298cd`. **No feature code has been
written.** Nothing in Phases 1–7 starts until this plan is approved.

How to read this: §1 is the state of the repo today, §2 is where the brief and the code
disagree, §3 is the list of decisions I need from you, §4 is the phase-by-phase file plan.
If you only read one section, read §3.

---

## 1. Where the repo actually is

### 1.1 Baseline gates at `f7298cd` (measured, before any change)

| Gate | Result |
|---|---|
| `ruff check` | **Fails** — 21 × E501 (line too long): 15 in `app/api/routes/architecture.py`, 6 in `scripts/generate_demo_pdf.py` |
| `ruff format --check` | **Fails** — the same 2 files would be reformatted |
| `mypy app` | Passes — 149 source files |
| `oxlint` | Passes — 0 errors, 19 warnings (`set-state-in-effect`, `only-export-components`, `exhaustive-deps`) |
| `vitest` | Passes — 2 files, 7 tests (needs a backend on :8000; the contract test fetches it) |
| `tsc -b && vite build` | Passes — eager bundle 216.89 kB gzip |
| `make no-stubs` | Passes |
| `pytest` | See §1.4 — run in progress when this was written |
| Playwright E2E | Not run in Phase 0 (needs minutes of real LLM time; will run before Phase 1 starts) |
| `make eval` / `make redteam` | Not run in Phase 0 |

So `make lint` is red before I touch anything. Both failing files were committed in earlier
work. Fixing them is the first item of Phase 1, because every later phase gate needs it green.

### 1.2 `backend/app/` — 10,560 lines of Python

```
main.py                      FastAPI app, lifespan (init_db, reconcile, preflight), 16 routers
api/routes/                  architecture audit chat council documents evaluation graph health
                             pii profiler redteam reports retrieval runs test_center trace
api/schemas/                 architecture audit chat council documents evaluation graph pii
                             profiler redteam retrieval test_center
agents/                      graph (LangGraph wiring) orchestrator runs state models tools
                             planner rewriter retriever critic summarizer synthesizer verifier
                             guardian context_utils
chunking/                    base models registry tokenization
  strategies/                fixed recursive sentence_window semantic structure_aware parent_child
core/                        config db errors events logging preflight tracing
council/                     models service
embeddings/                  registry
evaluation/                  benchmark datasets judge models report service
  metrics/                   retrieval
graphrag/                    communities extractor resolver service
guardrails/                  audit encoding injection input llama_guard output rate_limit retrieval
  redteam/                   attacks runner
ingestion/                   models refiner registry scraper service
  parsers/                   base docling_parser html_parser text_parser
  legacy/                    eml_parser office_legacy rtf_parser
llm/                         client json_utils router
privacy/                     detector models service tokenizer vault
profiler/                    advisor features service tournament
retrieval/                   compression dedupe hybrid hyde indexing reranker semantic_cache service
stores/                      bm25
  graph/                     base neo4j_store networkx_store
  vector/                    base chroma_store
```

All routes are mounted under `/api/v1`, except `WS /ws/trace/{session_id}`.

### 1.3 `frontend/src/` — 10,663 lines of TypeScript/CSS

```
App.tsx  main.tsx  index.css
pages/                 landing workspace architecture knowledge-graph evaluation test-center
                       _robot-preview
components/layout/     app-shell
components/architecture/  SystemDesignView DetailedSwimlaneView LightFlowDock NodeInfoCard
                          ArchIcons architectureLayout architectureExport lightFlowStages
                          traceStageMapping useArchitectureTopology (+2 vitest files)
components/evaluation/    EvalKpiCard RetrievalQualityChart ChunkingStrategyTable
                          RunHealthPanel EvaluationRail
components/knowledge-graph/  KnowledgeGraphCanvas ParticleTorusScene knowledgeGraphLayout
                             simplexNoise
components/workspace/  document-intelligence-panel ring-hero pipeline-facts
components/robot/      robot-character
components/showcase/   component-showcase future-phase-previews   (imported by no page)
components/ui/         alert-banner badge button card command command-palette dialog drawer
                       gauge glow-card input input-group separator skeleton sonner stat-card
                       state-message stepper textarea theme-toggle tilt-card tooltip
hooks/                 useDocumentStatus useTraceEvents
lib/                   api/client api/types motion raf-loop smooth-scroll theme utils
                       idb-storage (untracked, imported by nothing)
store/                 app-store
```

### 1.4 Tests

- Backend: 49 test modules plus `conftest.py` and `__init__.py` (the brief's "51"). They run
  real pipelines against real local models; the previous full run recorded in
  `docs/UI_ARCH_EVAL_KG_VALIDATION.md` was 257 passed in 10m9s.
- Frontend: 2 vitest files (7 tests) and 7 Playwright specs (plus a fixture and a README —
  the brief's "11").
- Nothing tests the Test Center: no backend test for its routes, no E2E spec.

Backend baseline for this plan: _filled in at the end of Phase 0 — see the hand-over message._

---

## 2. Where the brief and the code disagree

Each item says what the brief assumes, what the code shows, and what I propose. Items marked
**→ D_n_** need your decision (§3).

### Navigation and information architecture

**C1 — There is no Dashboard tab and no Guardrails tab. → D1**
The brief's final nav is Workspace · Dashboard · Architecture · Knowledge Graph · Evaluation ·
Guardrails. The real nav (`app-shell.tsx:12`) is Workspace · Architecture · Knowledge Graph ·
Evaluation · Test Center. `/app/dashboard` redirects to `/app` and `/app/guardrails` redirects
to `/app/evaluation` (`App.tsx:31,39`). Both tabs were removed on purpose in earlier work
(`docs/DECISIONS.md`, "Removing the Guardrails tab (TASK 4)"): the Dashboard's content went
into the Workspace right panel, the red-team suite into an Evaluation card, the audit log
into the Architecture drawer. `README.md` and `docs/ARCHITECTURE.md` still describe six
screens — they are stale. So Phase 6.2 is a new page, not a restyle, and the brief lists
Guardrails in the nav without describing its content anywhere.

**C2 — There is no "Evaluation Graph" tab.**
No such route or page exists and none ever did (zero grep hits). What exists is the knowledge
graph canvas embedded in the Evaluation page's right column. Phase 1.2 is therefore a no-op.
The embedded canvas does collide with Phase 3's right rail (advisor result, gate status, run
control) and with Phase 6.2, which puts an embedded KG on the Dashboard. Proposal: move it
from Evaluation to the Dashboard. No redirect is needed, since there is no old route.

**C3 — "System Design" is a toggle label, not a tab.**
The nav already says Architecture. The label lives in the in-page toggle
(`architecture-page.tsx:119`), the `view-mode-system` test id, the `SystemDesignView`
component name, two backend docstrings and one doc. All get renamed to Overview / Detailed.

**C4 — Test Center's backend routes are not shared, but its functions are. → D2**
`/test-center/self-test` and `/test-center/load-sample` serve only that page, so both go.
The self-test's check functions live in `core/preflight.py`, not in the route, so Phase 2.3's
"Run self-check" reuses them. "Load sample document" is the only one-click demo path in the
UI; deleting it outright loses a working feature.

**C5 — The app is single-document and forgets the document on reload.**
There is no `GET /documents` list route and no delete route. The frontend keeps one
`documentId` in a non-persisted Zustand store, so a reload lands on "Upload a document first"
on Architecture, Knowledge Graph and Evaluation. The brief's corpus stats, `document_ids: [...]`
in comparison, and "control room" Dashboard all need a document list. The local dev DB also
holds 285 documents, 211 of them copies of the Northwind sample left by test runs, so corpus
stats would be dominated by duplicates. Proposal: add `GET /api/v1/documents`,
`DELETE /api/v1/documents/{id}`, a document switcher in the shell, and a persisted selection
that is validated against the backend on load. This goes in Phase 1 because every later
phase benefits.

### API shape

**C6 — Route prefix.** The brief writes `/api/architecture/graph`, `/api/rag/strategies`,
`/api/rag/compare`, `/api/models/local`. Everything real is under `/api/v1`. I will use
`/api/v1/...` for all four.

**C7 — An architecture endpoint already exists.** `GET /api/v1/architecture/topology` returns
a hand-written list of 23 nodes and 28 edges (`routes/architecture.py:22-122`), including the
"API Gateway", "Trace Event Bus", "Shards", "Replicas" and "Workers" furniture the brief
objects to. It gets replaced by `/architecture/graph`, along with its schema, its backend
test, and the vitest contract test that pins the frontend's hand-placed coordinates to it.

### Architecture tab

**C8 — "Code-derived" can be literal for nodes and for the agent graph, not for every edge. → D5**
Three sources are genuinely introspectable: the packages under `app/` (via `pkgutil`), the
compiled LangGraph (`get_agent_graph().get_graph()` returns all nodes and edges — I checked),
and live config/health. Cross-module data-flow edges are not: they are implied by function
calls, and import direction is not data-flow direction. The honest design is to declare those
edges once in the backend and have a test prove each one is backed by a real import between
the two packages, so a declared edge cannot outlive the code. Deleting or disabling a
discoverable module then changes the payload with no frontend edit, which is the acceptance
test. Note the real agent graph has 10 nodes, not the 7 the brief lists: it also has
`guardian_in`, `decline` and `summarizer`. The diagram will show what the code has.

**C9 — The default Architecture mode today is timer-driven. → D3**
The page header promises "nothing is timer-driven", but `SystemDesignView` opens in "Demo
flow" mode, which walks comets along edges on a `setTimeout` loop with no backend event
behind them (`SystemDesignView.tsx:166, 287-304`). That contradicts the brief's rule 1 and its
"if the socket is closed, nothing pulses" criterion.

**C10 — Packet speed cannot be proportional to latency while the stage is still running.**
A stage's `duration_ms` only exists on its `done` event. So: on `running`, the node enters its
active state; on `done`, the packet travels the outgoing edge with a duration scaled (clamped,
log scale) from the measured duration of the stage that just finished. The animation is a
truthful replay of what just happened, lagging by its own length. I will say so in the UI
copy rather than imply real-time position.

**C11 — @xyflow/react has no layout engine. → D6**
The brief asks for "dagre/ELK-style layering via @xyflow/react". Neither dagre nor elkjs is
installed. xyflow renders and pans/zooms; it does not lay out.

**C12 — Per-node `invocation_count`, `last_latency_ms`, p50/p95 and "last 10 events" are not
stored anywhere.** `TraceBus` keeps per-session history in memory only. I will add a small
per-stage rolling aggregate to the bus, and label these numbers "since backend start".

**C13 — Health findings the new strip will expose on day one.**
- The BM25 index is in memory and only rebuilt during an ingest (`indexing.py:73`). After any
  backend restart it is empty, so "hybrid" search silently runs dense-only over the existing
  1,314 chunks until the next upload. This is a real bug today. It must be fixed (rebuild at
  startup) before strategy comparison means anything.
- `GRAPH_STORE=neo4j` and `VECTOR_STORE=qdrant` are read by nothing. Every caller imports the
  NetworkX store directly, and there is no Qdrant code at all. `/health` still echoes the
  setting. The graph-store pill will report what is actually in use and show Neo4j as
  `not_configured`; wiring the Neo4j adapter in is out of scope unless you want it.
- Several modules (chunking, profiler, evaluation) have nothing external to probe. Each node
  will state which kind of probe backs its status — import-only, functional, or dependency —
  so "healthy" never claims more than was checked.

**C14 — Concurrent local model inference crashes the backend on Apple Silicon.**
This is the crash from earlier in this session, and `docs/DECISIONS.md` records it as a known,
unfixed problem ("serializing GPU-bound model calls"). The self-check, parallel comparison on
the 16 GB tier, and re-indexing during chat all create exactly that concurrency. Proposal: one
process-wide lock around embedder, reranker and Docling inference. "Parallel" on 16 GB then
means LLM calls to Ollama fan out while local torch inference stays serialized.

### Evaluation

**C15 — The real metric names differ from the brief's.**
The benchmark computes faithfulness, correctness (against ground truth), citation validity,
precision@5, recall@5, hit@5, MRR, nDCG@5, p50/p95 latency, a production score and hard gates.
Answer relevance exists only for live chat turns. Proposal for the KPI row: Faithfulness ·
Answer relevance (added to the benchmark; the scoring function already exists) · Context
precision@5 · Context recall@5, with correctness and the rest in the table.

**C16 — Three places where the current harness reports numbers that were not measured.**
These break rule 1 today and would make Phase 4's comparison meaningless, so they are fixed
in Phase 3, before anything is built on them:
1. Retrieval-only configs never generate an answer. The "answer" scored for `bm25`, `dense`,
   `hybrid` and `hybrid_rerank_hyde` is the text of the top chunk (`benchmark.py:117`), so
   faithfulness is close to a tautology, and citation validity is hardcoded to `1.0`
   (`benchmark.py:122`).
2. When the judge model is unreachable or returns something unparsable, the score silently
   becomes `0.5` (`judge.py:46-54`). It should be "not measured" and excluded from the mean,
   with the count shown.
3. Every benchmark run generates a fresh question set (`evaluation/service.py:55`), so the
   existing "trend across runs" chart and "delta vs previous run" compare different questions.
   Runs must pin a saved eval set; a delta is shown only when both runs used the same one.

Consequence: numbers from runs made before this change are not comparable with later ones.
Old runs will be labelled as such, not silently mixed in. **→ D7 covers the stored data.**

**C17 — Benchmark runs are one blocking HTTP request.** There is no progress, no cancel, and
no eval-set or config choice. The brief needs streamed progress and cancellation here, for
comparison (4.4), for re-indexing (5), and for building indexes (4.2). I will build one
persisted background-job module (job row, numbered events, SSE stream, cancel, tier-aware
queue) modelled on the existing `ChatRun` pattern and use it for all four.

**C18 — A UI button rewrites a tracked doc.** `run_and_save_benchmark` rewrites
`docs/BENCHMARKS.md` on every run, including runs started from the Evaluation page (which is
why that file is currently modified in your working tree). Proposal: only `make eval` writes
it.

**C19 — `make eval` as a per-phase gate.** `make eval` exits non-zero unless some config
clears every hard gate. In the last documented run only `graph` did; the current
`BENCHMARKS.md` shows none did. After C16 the numbers will move again. I will report the
result honestly each phase and will not adjust thresholds to get a pass. If it fails for a
reason unrelated to the phase's change, I will show you and ask rather than block silently.

### Multi-RAG

**C20 — "Hybrid" is not the current default, and today's "hybrid" already reranks. → D8**
The default chat mode is `agentic` (`schemas/chat.py:9`, `workspace-page.tsx:135`). The
existing `hybrid` mode calls `hybrid_search_tool`, which hardcodes `rerank=True`
(`agents/tools.py:22`), so it is the brief's `hybrid_rerank`. Today's `graph` mode is graph
traversal only, with no vector leg. Proposed mapping: `agentic` → `agentic`, `agentic` +
council flag → `council`, `hybrid` → `hybrid_rerank`, `graph` → `graph_rag` (gains a vector
leg). The workspace default stays `agentic` so behaviour does not change on upgrade, and
"delta vs default" is computed against whatever the workspace default is at run time.

**C21 — Two strategies need chunks the document does not have.**
A document has one chunk set (recursive 512/64 unless the advisor's suggestion was accepted).
`naive` needs fixed-size chunks and `semantic_chunk` needs semantic chunks. Building all
variants at ingest would roughly triple ingest time. Proposal: make the index variant a
first-class key on chunk rows and vector metadata, and build a variant on demand with real
progress. This is the case the brief already allows for ("if a strategy needs a different
index, the UI says so and offers to build it"), so switching is instant once the index
exists. Ground truth for evaluation is transferred across chunkings by text overlap, which
the tournament already implements.

**C22 — An advisor and most of the features already exist.**
`profiler/features.py` computes token count, heading density, table/list/code ratios,
sentence and paragraph length, duplication ratio, OCR confidence, entity density and relation
density. `profiler/advisor.py` has a three-rule `recommend_mode`. To avoid two feature
extractors, I will extend `profiler/features.py` with what is missing (entity-type spread,
lexical diversity, cross-reference density, real page count, prose/tabular/slide class) and
put only the rule set and scoring in `rag_engines/advisor.py`. `recommend_mode` and the
`suggested_mode` / `mode_reason` fields are then superseded and removed. Two details:
`document_type` is guessed by an LLM, so no rule will depend on it; and entity density is
currently computed on the first 5,000 characters only, which I will replace with whole-document
counts from the NER pass ingestion already runs.

**C23 — Cost and tokens are not captured.** `llm/client.complete()` returns text only. I will
record real prompt/completion token counts from the provider response. For local models
"cost" is tokens and LLM-call count; a currency figure appears only for cloud models and is
labelled Estimated. `typical_latency_ms` in the registry is a declared constant, so it is
shown as Estimated until this machine has measured runs to replace it.

**C24 — Small samples are the norm for agent strategies.** Agent configs are capped at 5
samples per run (`benchmark.py:30`) and a council sample costs roughly 7 extra LLM calls. So
`agentic` and `council` comparisons will usually carry the "indicative, small sample" caveat
unless you raise the cap and accept the runtime.

### Models

**C25 — Embedding models are not Ollama models. → D9**
Embeddings use sentence-transformers from Hugging Face (`embeddings/registry.py`); the
reranker is a Hugging Face cross-encoder. So the embedding and reranker pickers cannot be
populated from Ollama. Ollama does report capabilities per model (`/api/show` returns
`['completion', 'tools']` for the chat models here), which is enough to keep embedding-only
and guard models out of the generator picker.

**C26 — Model settings are env-only and cached.** Switching at runtime needs a persisted
settings layer over the `.env` defaults (`.env` stays the zero-config path). Changing the
embedding model changes the vector dimension, and the Chroma collection is fixed at 384, so
each embedding model gets its own collection and each document records which model indexed
it. That record is what detects a mismatch.

### Workspace and Dashboard

**C27 — Much of the per-answer panel's data is not recorded today.**
- Retrieval funnel counts and why a chunk survived: `FusedHit` has the dense/BM25 ranks, but
  they are dropped before the answer is assembled. Needs a retrieval trace on the report.
- Page numbers: no chunker or parser ever sets `page`. **→ D10**
- Unsupported sentences: only the agentic verifier computes them, and it discards them after
  a revision. Showing them for every strategy costs one extra judge call per answer.
- Stage inputs/outputs: only some stages set previews (500 characters).
- Chat messages live in page-local state and are lost on tab switch — a known, logged,
  unfixed issue. Cross-tab links (citation → graph entity) make it matter more.

**C28 — Dashboard analytics need persistence.** Latency by stage, retry counts from the
critic/verifier loops, and per-stage timings exist only in the in-memory trace bus. Strategy
mix, zero-citation rate, grounding trend and guardrail trips can be computed from tables
that already exist (196 chat reports and the audit log are there now).

### Design system

**C29 — The default theme is light. → D4**
The brief says "keep the existing dark aesthetic". `index.html` applies `.light` unless dark
is stored, a deliberate earlier decision. Architecture and Evaluation are force-dark through
their own scoped palettes (`.theme-arch`, `.theme-eval`) that do not match the global tokens.
There are 117 literal colour values across 15 component files.

**C30 — Motion and dependency clean-up.** Current durations are 120/240/480/800 ms with a
different easing curve; they move to the brief's 120/200/320. Fonts (Inter + Space Grotesk)
and radii (12/16 px) already match. Lenis smooth scrolling wraps the whole app and caused
the earlier scroll bug; I propose limiting it to the landing page. `gsap` is installed and
imported nowhere, so it goes.

### Process

**C31 — Gate cost.** A full phase gate is roughly 10 minutes of `pytest`, several minutes of
Playwright, plus `make eval` and `make redteam`, all on real local models. Seven phases means
several hours of gate time alone. I will run the full gate at each phase boundary as asked,
and targeted tests while working.

**C32 — "60 fps with 40+ nodes".** The real node set will be around 30. I will measure frame
times with a Playwright trace and report the number; if I cannot measure it, the report will
say "not measured", as the previous report did.

**C33 — Working tree hygiene.** The tree has unrelated changes outside `assignment3/` (deleted
`day_01_fundamentals/`, root `README.md`, `.gitignore`; untracked `assignment2/`). Every
commit will stage only the `assignment3/` files that phase touched. **→ D11** covers three
loose items inside `assignment3/`.

---

## 3. Decisions I need from you

Each has a recommendation. "Approve with recommendations" is a complete answer.

| # | Decision | Recommendation |
|---|---|---|
| D1 | Dashboard and Guardrails: rebuild both as real pages, or keep today's merged layout and drop them from the nav? | Rebuild both. Guardrails = audit log, red-team suite, trip rate by category; Evaluation keeps a one-line safety summary. The Workspace panel becomes per-answer only. |
| D2 | "Load sample document": delete with the Test Center, or keep it as the Workspace first-run call-to-action? | Keep it in the Workspace empty state, served by a documents route. |
| D3 | Architecture "Demo flow" tour and the robot mascot riding the edges: remove? | Remove both. Replace the tour with "Replay", which re-plays a real recorded trace with its real timings and is labelled as a replay. The robot also leaves the Workspace panel when Phase 6.1 replaces it, so `robot-character.tsx` and its preview page are deleted. |
| D4 | Theme: dark by default with light kept as a supported option, or dark only? | Dark default, light kept. Once every surface is on tokens light costs little, and its contrast values were already verified. |
| D5 | Topology source: discovered packages + introspected LangGraph + declared-and-import-verified edges (C8)? | Yes. Full automatic edge inference would produce an import graph, not a data-flow diagram. |
| D6 | Layout: a small in-house layered layout (rank by stage, order by barycentre), or add `@dagrejs/dagre`? | In-house, no new dependency. I will come back to you if crossings look poor on the real graph. |
| D7 | Schema changes (new columns on documents, reports, benchmark runs): additive startup migration, or wipe `backend/var/data/` as the README currently advises? | Additive migration helper. There are 196 real chat reports and 8 benchmark runs locally that the Dashboard can show on day one. |
| D8 | Chat API: replace `mode` + `council` with `strategy` (breaking for any external caller), or keep the old fields as aliases? | Replace. Nothing outside this repo calls it, and aliases are the kind of dead code the brief rules out. |
| D9 | Embedding picker: offer the five sentence-transformers candidates already in the registry, or also add an adapter for Ollama embedding models? | Registry candidates only, each showing whether it is already downloaded. The Ollama adapter is a separate piece of work. |
| D10 | Page numbers on chunks: implement Docling page provenance now, or show section path and "page: not measured"? | Not measured for now; flag it in the validation report. Page provenance touches the parser, refiner and all six chunkers. |
| D11 | Loose files: (a) my uncommitted Apple-Silicon fix in `core/preflight.py`; (b) untracked, unused `frontend/src/lib/idb-storage.ts`; (c) untracked `OPTIMIZATION_LOG.md`. | (a) Commit it as its own `fix:` commit before Phase 1, then supersede it with the lock from C14. (b) and (c) left untouched unless you say they are mine to use or delete. |

Two things I am not asking about but want you to see: C16 changes what existing evaluation
numbers mean, and C13's BM25 bug means "hybrid" answers after a restart have been dense-only.

---

## 4. Phase plan

"New" means a file that does not exist today. Tests are listed with the code they cover.

### Phase 1 — Information architecture clean-up

Backend
- Fix the 21 lint errors and 2 format failures (`routes/architecture.py`,
  `scripts/generate_demo_pdf.py`).
- Delete `api/routes/test_center.py`, `api/schemas/test_center.py`; unregister in `main.py`.
- `api/routes/documents.py`, `api/schemas/documents.py`, `ingestion/service.py`: add list,
  delete, and (D2) sample-document routes. Tests in `tests/test_documents_api.py`.
- `stores/bm25.py`, `main.py`: rebuild BM25 at startup (C13). Test in
  `tests/test_hybrid_retrieval.py`.
- New `core/inference_lock.py`; applied in `embeddings/registry.py`, `retrieval/reranker.py`,
  `ingestion/parsers/docling_parser.py`; `core/preflight.py` simplified back (C14).

Frontend
- Delete `pages/test-center-page.tsx`; remove its route, nav item, client functions and types.
- `App.tsx`, `components/layout/app-shell.tsx`: final nav; D1 pages as honest empty shells
  until Phases 6 and 3 fill them (or omitted from the nav until then — your call under D1).
- `store/app-store.ts`: persisted document selection; new document switcher in the shell.
- `pages/architecture-page.tsx`: toggle label and test id to Overview / Detailed.
- E2E: `smoke.spec.ts` updated for the nav and redirects.

Docs: `README.md`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/USAGE.md`,
`docs/UI_ARCH_EVAL_KG_VALIDATION.md` (Test Center and "System Design" references).

### Phase 2 — Architecture tab

Backend
- New `app/architecture/` (`discovery.py`, `manifest.py`, `status.py`): node discovery,
  LangGraph introspection, declared edges, per-node probes and config.
- Replace `api/routes/architecture.py` and its schema with `GET /architecture/graph`.
- `core/tracing.py`: per-stage rolling aggregates and a recent-events buffer (C12).
- `api/routes/health.py`: per-subsystem probes with timings and raw results; new
  `POST /health/self-check` (tiny embed, tiny retrieval, one-token generation).
- Tests: rewrite `tests/test_architecture_api.py` (every node path importable; every declared
  edge backed by an import; a removed module disappears; disabled is distinct from broken);
  extend `tests/test_health.py`; `tests/test_trace_ws.py` for aggregates.

Frontend
- Delete `SystemDesignView.tsx`, `architectureLayout.ts`, `lightFlowStages.ts`,
  `traceStageMapping.ts`, `LightFlowDock.tsx`, `ArchIcons.tsx`,
  `architectureLayout.contract.test.ts`, `lightFlow.test.ts`.
- New under `components/architecture/`: graph hook, layered layout (+ vitest), node and edge
  renderers, the three views over one graph, health strip, node drawer, trace-follow camera.
- Keep and adapt `architectureExport.ts` (PNG, SVG, plus JSON of the payload).
- `hooks/useTraceEvents.ts`: expose socket state so a closed socket visibly stops everything.
- E2E: replace `architecture-light-flow.spec.ts` (renders from payload; closing the socket
  stops pulses and flips the chip; stopping Ollama turns its pill red is a manual check,
  documented with evidence).

Docs: `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/UI_MOTION.md`.

### Phase 3 — Evaluation tab

Backend
- New `core/jobs.py` and `api/routes/jobs.py`: persisted jobs, event stream, cancel, queue.
- `evaluation/benchmark.py`, `judge.py`, `service.py`, `models.py`, `datasets.py`: real
  generation for every config, "not measured" instead of `0.5`, pinned eval sets, answer
  relevance, run metadata (eval set, n, judge model, config snapshot); stop rewriting
  `BENCHMARKS.md` from the API (C16, C18).
- `api/routes/evaluation.py` and schema: list eval sets, start run as a job, list runs
  across documents.
- Tests: `test_evaluation_benchmark.py`, `test_evaluation_api.py`, `test_eval_judge.py`, new
  `test_jobs.py`.

Frontend
- Rebuild `pages/evaluation-page.tsx` to the brief's layout; rewrite the five
  `components/evaluation/*` files onto shared components; move the KG canvas out (C2).
- E2E: update `evaluation-dashboard.spec.ts`.

Docs: `docs/EVALUATION.md`, `docs/API.md`.

### Phase 4 — Multi-RAG engines (three commits: 4a registry and switching, 4b advisor, 4c comparison)

Backend
- New `app/rag_engines/`: `base.py` (protocol), `registry.py`, `strategies.py` (the eight
  compositions over existing building blocks), `availability.py`, `advisor.py`, `compare.py`.
- `agents/orchestrator.py`, `agents/tools.py`, `api/routes/chat.py`, `api/schemas/chat.py`,
  `agents/models.py`, `retrieval/semantic_cache.py`: `strategy` replaces `mode` (D8); the
  report records strategy, models, tokens and the retrieval trace.
- `chunking/models.py`, `retrieval/indexing.py`, `stores/bm25.py`,
  `stores/vector/chroma_store.py`: index variants (C21).
- `llm/client.py`: token accounting (C23).
- `profiler/features.py` extended; `profiler/advisor.py`, `profiler/service.py`,
  `api/schemas/profiler.py`: mode suggestion removed (C22).
- New `api/routes/rag.py`: strategies, per-document recommendation, workspace default,
  compare (as a job, cached by corpus hash + strategy + eval set), build-index.
- Tests: new `test_rag_registry.py`, `test_rag_strategies.py`, `test_rag_advisor.py`,
  `test_rag_compare.py`, `test_rag_api.py`; updates to `test_chat_api.py`,
  `test_agents_*.py`, `test_semantic_cache.py`, `test_profiler_*.py`.

Frontend
- Workspace strategy picker, "Answered with" label, recommendation card after ingest,
  build-index prompt; new comparison view with cost estimate, confirmation, progress, cancel,
  winner banner and Adopt. E2E: new `rag-strategies.spec.ts`; `chat.spec.ts` updated.

Docs: `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/USAGE.md`, `docs/EVALUATION.md`.

### Phase 5 — Local model selection

Backend: new `llm/models_catalog.py` and `api/routes/models.py`; new `core/runtime_settings.py`
(C26) read by `llm/client.py`, `llm/router.py`, `council/service.py`, `evaluation/judge.py`,
`embeddings/registry.py`, `retrieval/reranker.py`; per-model Chroma collections; re-index job.
Tests: new `test_models_api.py`, `test_runtime_settings.py`; `test_model_router.py`,
`test_council.py` updated.

Frontend: model picker in the Workspace header and a Settings surface; tier-budget warning;
index-mismatch warning with re-index progress; exact Ollama start command when it is down.
E2E: new `model-picker.spec.ts`.

Docs: `docs/API.md`, `docs/USAGE.md`, `.env.example` notes.

### Phase 6 — Workspace and Dashboard

Backend: retrieval funnel and per-chunk provenance on the report; sentence-level grounding;
persisted stage timings (C27, C28); new `api/routes/analytics.py`; corpus-level graph stats
in `api/routes/graph.py`. Tests: new `test_analytics_api.py`; `test_graph_api.py`,
`test_chat_api.py` extended.

Frontend: replace `components/workspace/document-intelligence-panel.tsx`, `ring-hero.tsx`,
`pipeline-facts.tsx` with the per-answer analysis panel; chat state moved into the store;
new `pages/dashboard-page.tsx` (and `pages/guardrails-page.tsx` under D1);
`pages/knowledge-graph-page.tsx` accepts a focused-entity link. E2E: new `dashboard.spec.ts`;
`workspace-scroll.spec.ts` and `chat.spec.ts` updated.

Docs: `docs/USAGE.md`, `docs/API.md`.

### Phase 7 — Design system, polish, accessibility

Frontend: new `styles/tokens.css` (single source; `index.css` imports it); `lib/motion.ts` to
the new scale; one each of Card, StatCard, DataTable, Badge, Drawer, Toast, EmptyState,
LoadingState; remove `glow-card`, `tilt-card` (landing uses it — replaced), `gauge` if
unused by then, `components/showcase/*`; all literal colours onto tokens; real command
palette actions (the "example toast" item goes); tooltips for every metric; chart table
fallbacks; reduced-motion pass; Lenis limited to the landing page; `gsap` removed from
`package.json`. E2E: new `a11y-motion.spec.ts` (reduced motion, keyboard path, no
`Math.random` or literal metric values in data paths — a grep-backed check).

Docs: `docs/UI_MOTION.md`, `docs/DECISIONS.md`, and `docs/VALIDATION_REPORT.md` with the
itemized pass/fail for every requirement, including everything not implemented and why.

---

## 5. Things I would do differently from the brief

1. **Fix the evaluation harness before building comparison on it** (C16). Otherwise Phase 4
   would present confident deltas between numbers that were never measured.
2. **Build the background-job module once, in Phase 3** (C17), instead of four separate
   progress/cancel mechanisms in Phases 3, 4 and 5.
3. **Serialize local inference before adding concurrency** (C14). The brief's 16 GB
   "parallel" tier would otherwise reintroduce the crash that took the backend down today.
4. **Build index variants on demand** (C21) instead of at ingest.
5. **Add document list and persistence in Phase 1** (C5). The brief assumes a corpus; the UI
   today has one document that vanishes on reload.

## 6. What this plan deletes

Listed in one place so nothing is removed by surprise: the Test Center page and its two
routes; the existing topology endpoint and its contract test; the hand-authored Architecture
canvas (six files and two vitest files, 1,540 lines); under D3 the demo tour and
`robot-character.tsx` with its preview page; the Workspace's ring hero, pipeline facts and
analyst panel (their data moves into the new panel and the Dashboard); `recommend_mode` and
its two response fields; the unused `components/showcase/` (841 lines), `glow-card`,
`tilt-card`; the `gsap` dependency; the `mode` and `council` chat request fields under D8.
