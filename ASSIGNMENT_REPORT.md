# Assignment 3 report — Veritas

**Vinay Kumar · AI Engineering Bootcamp, Week 3 (Days 11–15)**

Veritas is a dynamic hybrid RAG pipeline that runs entirely on a laptop. It ingests documents in
any common format, masks personal data before anything is stored, indexes the text for dense,
keyword and graph retrieval, and answers questions with a citation on every claim. Its central
idea: no single RAG strategy is best for every document, so after each upload Veritas writes
questions with known answers from that document, runs several strategies on them, scores every
answer, and answers that document with the measured winner. Any other strategy can be compared
against it, question by question, with the scores side by side.

This report maps every Week 3 topic to what was built, where it is in this folder, and the
evidence that it works. Every number in it comes from a run on this code; the commands to
reproduce them are in section 9.

---

## 1. At a glance

| | |
|---|---|
| Stack | FastAPI, LangGraph, LiteLLM + Ollama (`llama3.2:3b`, `llama-guard3:1b`), sentence-transformers (`all-MiniLM-L6-v2`), cross-encoder `ms-marco-MiniLM-L-6-v2`, ChromaDB / Qdrant, BM25, NetworkX / Neo4j, Docling, spaCy, Presidio, React 19 + TypeScript |
| Size | 19,000 lines of Python in 175 modules; 14,500 lines of TypeScript; 58 REST endpoints plus SSE streaming and a trace WebSocket |
| Tests | 458 backend tests (pytest), 28 frontend unit tests (Vitest), 32 end-to-end tests (Playwright) against the real backend and models |
| Coverage | 81% of backend lines, measured without the language model |
| Retrieval strategies | 8: Naive, Hybrid, Hybrid + Rerank, HyDE, Semantic chunks, GraphRAG, Agentic, Council |
| Best measured result | Agentic RAG passes every production gate: faithfulness 0.87, correctness 0.82, Recall@5 1.00, p95 13.7 s |
| Safety | 41/42 red-team attacks blocked (97.6%), 1/15 harmless prompts blocked (6.7%), 0 PII values in the index |
| Retrieval check | 31 hand-written questions over 4 real documents (incl. French and a 61-page handbook): every answer's evidence is in the top 5 |
| Development history | More than 40 commits from 11 to 14 October 2026, included in this folder (`git log`) |

---

## 2. How it fits together

```
Upload ─► Parse ─► Refine ─► PII vault ─► Chunk ─► Embed ─► Index (ChromaDB/Qdrant + BM25)
                                            └────► Knowledge graph (NetworkX/Neo4j)
                                                        │
                    Measure strategies on generated questions ─► best strategy per document
                                                        │
Question ─► Input guardrails ─► Retrieve / rerank / traverse / agent ─► Answer with citations
         ─► Output guardrails ─► Per-sentence grounding score ─► streamed to the UI
```

Every arrow is a real trace stage (`app/core/tracing.py`), streamed over `WS /ws/trace`; the
Architecture tab animates from those events. Code is layered: `app/api/routes` (thin HTTP),
`app/api/schemas` (Pydantic contracts), and services per domain (`ingestion`, `privacy`,
`chunking`, `retrieval`, `graphrag`, `agents`, `rag_engines`, `evaluation`, `guardrails`).

---

## 3. Day 11 — Custom parsers, chunking, vector DBs and hybrid search

### 3.1 Parsers and legacy formats

**Built.** One registry maps each extension to a parser (`app/ingestion/registry.py`):

| Format | Parser | How |
|---|---|---|
| PDF, DOCX, PPTX, XLSX, PNG/JPG/TIFF | Docling (`parsers/docling_parser.py`) | Layout-aware parsing: headings, reading order, tables as Markdown, OCR for scanned pages |
| HTML | trafilatura (`parsers/html_parser.py`) | Main-content extraction, boilerplate removed |
| EML | `legacy/eml_parser.py` | Headers and body from the standard library |
| RTF | `legacy/rtf_parser.py` | Control words stripped |
| Legacy binary .doc / .xls | `legacy/office_legacy.py` | Converted with headless LibreOffice, then parsed by Docling / the CSV parser; a clear, actionable error if LibreOffice is absent |
| Markdown, TXT, CSV | `parsers/text_parser.py` | CSV becomes a Markdown table |
| URL | `ingestion/scraper.py` | SSRF-guarded fetch (private-network addresses refused) |

After parsing, a **refiner** (`ingestion/refiner.py`) repairs text: de-hyphenation, page
numbers, repeated headers/footers, broken paragraphs, and near-duplicate removal, with a
before/after quality score and a log of every fix.

**Evidence.** `tests/test_parsers_formats.py` parses a real file of every format (DOCX with a
table, PPTX slides, XLSX rows, RTF, legacy .doc/.xls through LibreOffice — CI installs it), OCR
of a scanned page with no text layer, a 61-page PDF, and a corrupt file that must fail with a
message a user can act on. `test_ingestion_service.py` covers empty, zero-byte, corrupt and
password-protected uploads, stage timeouts, cancel and retry.

### 3.2 Chunking

**Built.** Six strategies (`app/chunking/strategies/`), all measured in tokens of the embedding
model's own tokenizer:

| Strategy | Idea |
|---|---|
| `fixed` | Fixed token windows with overlap |
| `recursive` (default, 512/64) | Split on paragraph → line → sentence → word, pack to the size, carry overlap |
| `sentence_window` | Windows of whole sentences (5, stride 3) |
| `semantic` | Break where consecutive sentence embeddings diverge |
| `structure_aware` | Respect the Markdown section tree Docling produces |
| `parent_child` | Small children for retrieval, large parents for context |

A **chunking tournament** (`app/profiler/tournament.py`) profiles each document and measures
five candidate chunkings against a synthetic question set; the Evaluation tab shows the result
and can re-index with the winner.

**Decision worth noting.** Chunk text is cut from the original by the tokenizer's character
offsets, never decoded from tokens: MiniLM's tokenizer is uncased, and decoding lowercased and
re-spaced the text (see section 8).

### 3.3 Vector databases and hybrid search

**Built.**
- **Embeddings:** local `sentence-transformers/all-MiniLM-L6-v2` (`app/embeddings/`).
- **Two vector stores behind one interface** (`app/stores/vector/`): ChromaDB (default) and
  Qdrant, both embedded on disk with no server; `VECTOR_STORE=qdrant` switches, and
  `QDRANT_URL` points at a server instead. Filters, deletes and scores are identical.
- **Hybrid search** (`app/retrieval/hybrid.py`): dense results and BM25 (bm25s) keyword results
  fused with **Reciprocal Rank Fusion** (k = 60). Both indexes are written in one path, so they
  cannot drift apart.

**Evidence.** `test_vector_stores.py` loads the same vectors into both stores and requires the
same hits, in the same order, with the same scores; CI then runs the whole retrieval and
ingestion suite a second time on Qdrant. `test_hybrid_retrieval.py` checks the fusion.

---

## 4. Day 12 — Advanced RAG and reranking

**Built.**
- **Cross-encoder reranking** (`retrieval/reranker.py`): `ms-marco-MiniLM-L-6-v2` re-scores the
  fused candidates (fetched at 4× k so the reranker has something to choose from).
- **HyDE** (`retrieval/hyde.py`): the question is answered hypothetically and that answer is
  embedded, which retrieves better when questions and documents are phrased differently.
- **Query rewriting** (`agents/rewriter.py`): when the agent's critic judges the evidence
  insufficient, it retries with a different technique each time — HyDE, step-back, multi-query.
- **Context deduplication** (`retrieval/dedupe.py`): MMR (relevance vs diversity), a cosine
  threshold, and n-gram overlap; plus **extractive compression** to a token budget
  (`compression.py`) and a **semantic cache** for repeated questions (`semantic_cache.py`).
- **Eight strategies in one registry** (`app/rag_engines/registry.py`), each a declarative plan
  (retrieval mode, rerank, HyDE, chunking variant, graph, agent). Strategies that need an index
  variant or a graph build it on demand, with progress.
- **Agentic RAG** (`app/agents/graph.py`): a LangGraph state machine — guardian (in) → planner →
  rewriter → retriever → critic → synthesizer → verifier → guardian (out). The critic can send
  it back to rewrite up to 3 times; the verifier checks each sentence against the context and
  can request one revision, after which unsupported sentences are removed. Broad questions
  ("history of …") take a map-reduce summarizer path over a diversity-selected sample.
- **LLM Council** (`app/council/`): independent answers from several models, anonymised peer
  review, a chairman synthesis and a computed agreement score (opt-in; it loads extra models).

**Evidence.** `test_reranker.py`, `test_hyde.py`, `test_dedupe.py`, `test_compression.py`,
`test_semantic_cache.py`, `test_agents_*.py` (each node and the compiled graph), `test_council.py`,
and the golden retrieval test (section 6.3). The measured effect of each technique is in the
benchmark (section 6.1).

---

## 5. Day 13 — Knowledge graphs

**Built.**
- **Entity extraction** (`graphrag/extractor.py`): spaCy NER for entities; masked PII tokens kept
  as entities of their own type, so relations to a (masked) person are not lost; relation
  triples from the LLM with a strict JSON contract, parsed tolerantly (a reply cut off by the
  token limit keeps every complete triple).
- **Entity resolution** (`graphrag/resolver.py`): mentions merged only within the same NER
  label and only when both embedding similarity and fuzzy string similarity agree ("Jane Smith"
  vs "J. Smith" merge; "Jane Smith" vs "Jane Doe" do not).
- **Two graph stores behind one interface** (`app/stores/graph/`): NetworkX (default, persisted
  to disk) and Neo4j (`GRAPH_STORE=neo4j`).
- **Traversal** (`graphrag/service.py`): entities named in the question are linked by fuzzy
  matching, then the graph is walked n hops in both directions; the path and the source chunks
  feed the GraphRAG answer.
- **Communities**: Louvain clustering, each community summarised by the LLM.
- **In the UI**: an interactive graph with entity inspection, most-connected entities, and "Ask
  the graph", which lights up the traversal while a real answer is written.

**Evidence.** `test_graph_store_parity.py` runs one set of expectations against both stores —
merge across documents, question linking, hop-limited traversal both ways, per-document edges,
removal, communities; CI runs it against a real Neo4j service container.
`test_graphrag_*.py` cover extraction, resolution and the service; the end-to-end suite asks the
graph a question in the browser.

---

## 6. Day 14 — AI evaluations

### 6.1 Benchmark across strategies (`make eval` → `docs/BENCHMARKS.md`)

**Synthetic dataset generation** (`evaluation/datasets.py`): questions with known answers are
written from the document's own chunks in five categories — factoid, multi-hop (two linked
chunks), comparison, unanswerable, and PII — each keeping the ids of its source chunks.
Questions are de-duplicated by embedding, and any that refer to "the excerpt" or "both texts"
are rejected, since no user would ask them.

**Metrics.** Retrieval: Precision@5, Recall@5, MRR and nDCG@5 against the source chunks
(`evaluation/metrics/retrieval.py`). Generation, by a judge model: faithfulness (claims
supported by the cited passages, in full), relevancy, correctness against the known answer
(`evaluation/judge.py`). An answer that claims the document lacks a stated answer scores 0 for
correctness.

Latest run, bundled HR handbook, 10 questions per strategy (6 for the agent):

| Strategy | P@5 | Recall@5 | MRR | nDCG@5 | Faithfulness | Relevancy | Correctness | p95 | Score |
|---|---|---|---|---|---|---|---|---|---|
| Naive | 0.30 | 0.90 | 0.95 | 0.87 | 0.64 | 0.71 | 0.63 | 9.4 s | 0.60 |
| Hybrid | 0.35 | 1.00 | 1.00 | 1.00 | 0.62 | 0.69 | 0.59 | 6.1 s | 0.62 |
| Hybrid + Rerank | 0.35 | 1.00 | 1.00 | 1.00 | 0.67 | 0.69 | 0.64 | 4.5 s | 0.66 |
| HyDE | 0.35 | 1.00 | 0.95 | 0.96 | 0.80 | 0.85 | 0.81 | 11.0 s | 0.70 |
| Semantic chunks | 0.20 | 0.80 | 1.00 | 0.85 | 0.62 | 0.76 | 0.61 | 3.7 s | 0.62 |
| GraphRAG | 0.35 | 1.00 | 0.95 | 0.96 | 0.68 | 0.82 | 0.73 | 4.0 s | 0.69 |
| **Agentic** | 0.33 | 1.00 | 1.00 | 1.00 | **0.87** | **0.93** | **0.82** | 13.7 s | **0.71** |

Reading it: hybrid retrieval with reranking already finds the right passage every time
(Recall@5 1.00, MRR 1.00), so the differences are in generation. HyDE and the agent's
verify-and-revise loop raise faithfulness; the agent is the only one over the 0.85 gate, at
about three times the latency of Hybrid + Rerank. (Each question is written from one or two
chunks, so Precision@5 cannot exceed 0.2–0.4.)

### 6.2 Selection criteria for production

Two steps, so a fast but unreliable strategy can never win on speed (`evaluation/benchmark.py`):

1. **Hard gates**, all required: faithfulness ≥ 0.85, red-team injection block rate ≥ 95%, zero
   PII values in the indexed chunks, p95 latency ≤ 15 s.
2. **Weighted score** among those that pass: 0.35 × faithfulness + 0.25 × correctness + 0.15 ×
   nDCG@5 + 0.15 × safety − up to 0.10 for latency. If none passes, the best is shown, labelled
   as not production-ready.

The same idea runs **per document inside the app** (`rag_engines/document_strategy.py`): after
each upload the fast strategies are measured on five questions from that document and the best
becomes its strategy. A slower winner (Agentic, Council) is recommended with the reason but
never switched to automatically. **Comparisons** (`rag_engines/compare.py`) are cached by
document content, strategy, question set and model configuration, so re-opening one is
instant and adding a strategy runs only that strategy. Every score shows the number of
questions it rests on; under ten is labelled a small sample. Scores are labelled *Verified*
(against a known answer) or *Estimated* (judge only).

### 6.3 Golden retrieval test

`tests/test_golden_retrieval.py`: 31 hand-written questions over four real documents — a
two-page PDF, a DOCX, a French PDF and a 61-page handbook with facts placed in its last
chapters. Each question carries a verbatim evidence quote from its document; the document is
ingested through the real pipeline and a chunk containing the quote must be in the top 5 of
hybrid search with reranking. All 31 pass. It needs no language model, so it runs in CI.

### 6.4 Live quality on every answer

Each answer in the UI is scored after it streams: faithfulness and relevancy by the judge, and
per-sentence grounding (`evaluation/grounding.py`) — unsupported sentences are underlined.
The Evaluation tab aggregates these by day and strategy, with time per pipeline stage.

---

## 7. Day 15 — Security and guardrails

Three layers plus the PII vault (`app/guardrails/`, `app/privacy/`); every decision, including
`allow`, is written to an audit log (`GET /api/v1/audit`) linked to its trace.

| Layer | Checks |
|---|---|
| **Input** | Rate limit per session and per client address (Redis-backed when `REDIS_URL` is set; 429 with Retry-After); length, zero-width characters and decodable base64 payloads (`encoding.py`); prompt injection by regex heuristics, then the `protectai/deberta-v3-base-prompt-injection-v2` classifier (`injection.py`); Llama Guard 3 for unsafe content |
| **Retrieval** | Every retrieved chunk scanned for indirect injection; all context wrapped in untrusted-data delimiters with an instruction hierarchy in the system prompt |
| **Output** | Secret / system-prompt leak block; PII redaction for anything not already in the source passages; Llama Guard on the answer; answers without citations escalated |
| **Request validation** | Pydantic v2 models on every request and response; uploads limited to 25 MB and to known formats |

**PII detection** (`app/privacy/detector.py`): Presidio with spaCy NER, restricted to personal
data types (names, emails, phones, IPs, cards, IBAN, SSN, Aadhaar, PAN) so organisations and
places stay available to the knowledge graph. Added recognizers: a given-name recognizer for
names the small NER model misses, and an email pattern that accepts internal domains. On
non-English documents the English NER's person guesses are not used, and any person span must
look like a name. Values are replaced by deterministic HMAC tokens (`<PERSON_a1b2c3>`) before
chunking, so embeddings, indexes, the graph and the model never see them; originals sit in a
Fernet-encrypted vault, revealed only through an audited endpoint.

**Llama Guard and the injection classifier are complementary, not redundant**: a jailbreak-
framed request for lock-picking passes Llama Guard (not one of its categories) but the
classifier flags it at 99.9997%; a plain violent request has no jailbreak framing but Llama
Guard flags it (S1).

**Evidence.** The red-team suite (`guardrails/redteam/`, `make redteam`, also a CI gate):

| Category | Blocked |
|---|---|
| Direct injection | 10/10 |
| Jailbreak | 9/10 |
| Indirect injection (in documents) | 8/8 |
| PII exfiltration | 8/8 |
| Encoding tricks | 6/6 |
| **Total** | **41/42 (97.6%)**, false positives 1/15 (6.7%) |

Plus `test_guardrails_*.py` for every layer, `test_pii.py` and `test_scraper_ssrf.py`, and the
benchmark's scan of every indexed chunk for PII (0 found).

---

## 8. Defects found by measuring, and fixed

The evaluation tooling was used on the system itself; these were real defects it exposed,
each with a regression test:

| Found by | Defect | Fix |
|---|---|---|
| Benchmark PII scan | Chunk overlap was decoded from tokens; the uncased tokenizer lowercased text and broke mask tokens into `< person _ b43251 >` | Chunks cut from the original text by character offsets |
| Benchmark faithfulness | Faithfulness was judged against citation previews (first 300 characters of each passage) | Judged against the full cited passages |
| Agent traces | Ollama's default 4096-token window silently cut the instructions off long agent prompts | Explicit 8192-token window on every call |
| Agent traces | The evidence critic answered UNANSWERABLE to everything on the 3B model, so every question retried to the limit | Yes/no wording the model follows, plus a confident reranker score accepted on its own |
| Golden retrieval test | Near-duplicate paragraph removal dropped templated paragraphs whole: a 61-page handbook kept 6% of its text | A paragraph is removed only if all its sentences already appeared |
| Golden retrieval test | The English NER masked "bénéficie de seize semaines de congé payé" as a person in a French document | Language-aware detection and a name-shape check |
| Screenshot review | Names and internal-domain emails the small NER missed reached the knowledge graph | Given-name and any-domain email recognizers |
| Knowledge graph test | Relation replies cut off by the token limit were rejected whole, leaving the sample with no relations | Every complete triple is kept |

---

## 9. Engineering quality

- **Tests.** 458 backend tests on real pipelines, no mocked backend logic. 35 call a local model
  and are marked `needs_ollama`; where Ollama is absent they are skipped with a reason, and the
  other 416 pass (81% coverage). With Ollama running, all 35 pass as well (about 6 minutes);
  the Neo4j and Redis tests run against real servers in CI. 28 Vitest unit tests; 32 Playwright end-to-end tests that
  drive the real UI against the real backend and models.
- **CI** (`.github/workflows/ci.yml`): ruff lint and format, mypy, the pytest suite, the
  retrieval suite again on Qdrant, a job with real Neo4j and Redis service containers, the
  red-team gate (≥ 95% blocked, ≤ 10% false positives), and the frontend's lint, unit tests and
  production build. All jobs pass.
- **Typing.** mypy clean on all 175 modules; Pydantic v2 at every API boundary; strict
  TypeScript with a typed API client.
- **Containers.** `docker-compose.yml` runs backend and frontend; `qdrant` and `neo4j` profiles
  start those servers. Each service has a Dockerfile.
- **Observability.** Every stage emits a trace event; per-stage latency is recorded and charted;
  `/health` and `/health/subsystems` probe each dependency; a self-check runs the pipeline end
  to end.
- **Reliability.** Ingestion runs as cancellable background jobs with timeouts and retries;
  model calls have a latency budget with fallback; work that does not block chat (graph,
  profiling, measurement) runs at lower priority.
- **Development history.** More than 40 commits over four days in this folder's `.git`, each a focused
  change with a descriptive message (`git log --stat`).
- **Documentation.** `README.md` (overview, topic map, results), `docs/ARCHITECTURE.md`,
  `API.md`, `USAGE.md`, `EVALUATION.md`, `GUARDRAILS.md`, `BENCHMARKS.md` (generated), and
  `DECISIONS.md`, which records every non-obvious choice with the evidence behind it.

**Reproduce the numbers** (Python 3.11 with uv, Node 22, Ollama with `llama3.2:3b` and
`llama-guard3:1b`):

```bash
make setup && make dev        # UI at http://localhost:5173/app
make test                     # backend and frontend test suites
make eval                     # benchmark → docs/BENCHMARKS.md (about 25 minutes)
make redteam                  # red-team suite
cd frontend && npx playwright test   # end-to-end, about 15 minutes
```

---

## 10. Feedback from earlier assignments, addressed here

| Earlier feedback | In this assignment |
|---|---|
| Single commit, no iterative history (Week 1) | More than 40 focused commits over four days, included in the folder |
| No Docker or CI (Week 1) | Dockerfiles, docker-compose with profiles, and a five-job CI workflow that passes |
| N+1 queries (Week 1) | Dashboard and audit statistics are `GROUP BY` / `COUNT` aggregates in single queries; document lists are one query plus a count |
| No native tool calling (Week 2) | Partly: the agent's planner chooses among four retrieval tools (hybrid search, graph traversal, PII vault lookup, metadata filter) and LangGraph routes to them, but the choice is a validated JSON contract rather than the provider's native tool-calling API |
| In-memory rate limiting when Redis is off (Week 2) | Per-client limits with a Redis backend tested against a real Redis in CI; memory is only a fallback during a Redis outage |
| SQLite limits concurrency (Week 2) | Still SQLite (single-user local tool), accessed through async SQLAlchemy; the heavy data lives in the vector and graph stores |

---

## 11. Limitations, stated plainly

- The judge is the same local 3B model that answers, so judged scores are noisier than with a
  large hosted judge; every score carries its sample size, and retrieval metrics (which need
  no judge) are reported separately.
- Agentic RAG is the most faithful strategy but takes 11–14 s per answer on a laptop; it is
  recommended when it wins, never switched to silently.
- The given-name recognizer covers common names in a fixed list; an unusual name the NER model
  also misses can go unmasked. The output layer still redacts PII in answers.
- The app is single-user: no authentication or roles, by design for a local tool.
- 36 frontend lint warnings (React style rules) remain; lint, type-check and build pass.

---

## 12. Where to look

| To see | Open |
|---|---|
| Overview and topic → code map | `README.md` |
| This report | `ASSIGNMENT_REPORT.md` |
| Benchmark results | `docs/BENCHMARKS.md` |
| Why each choice was made | `docs/DECISIONS.md` |
| Parsers | `backend/app/ingestion/` |
| Chunking | `backend/app/chunking/` |
| Vector stores, hybrid search, reranking, HyDE, dedup | `backend/app/stores/vector/`, `backend/app/retrieval/` |
| Strategies, per-document selection, comparisons | `backend/app/rag_engines/` |
| Agent | `backend/app/agents/` |
| Knowledge graph | `backend/app/graphrag/`, `backend/app/stores/graph/` |
| Evaluation | `backend/app/evaluation/` |
| Guardrails and PII | `backend/app/guardrails/`, `backend/app/privacy/` |
| Tests | `backend/tests/`, `frontend/tests/e2e/` |
| Screenshots | `docs/screenshots/` |
