# Veritas

An adaptive, agentic RAG platform: hybrid search, reranking, GraphRAG, an LLM council, layered
guardrails, automated evaluation, and a real-trace-driven React interface — free and local by
default (Ollama), with optional cloud LLMs via env vars.

**Status: all 13 build phases have working code and real tests** — backend (ingestion through
LLM Council) and a six-screen frontend (Workspace, Dashboard, Architecture, Knowledge Graph,
Evaluation, Guardrails) plus a landing page. See
[docs/VALIDATION_REPORT.md](docs/VALIDATION_REPORT.md) for the honest, itemized pass/fail
account of what's verified vs. simplified vs. not attempted — several things described in the
original brief (a GSAP-driven Cinematic Tour, a recorded hero video, Lighthouse/axe scores)
were deliberately cut for time and are called out there, not silently skipped. See
[docs/DECISIONS.md](docs/DECISIONS.md) for every default chosen along the way and why.

## Quickstart

```bash
# 1. Backend
cd backend
uv sync
cp ../.env.example ../.env   # defaults are free/local; edit if you want cloud LLMs
uv run uvicorn app.main:app --reload --port 8000

# 2. Pull the local models (first run only)
ollama pull llama3.2:3b              # default/fast model + chairman
ollama pull qwen2.5:7b-instruct      # council member / stronger model-router target
ollama pull gemma2:2b                # second council member
ollama pull llama-guard3:1b          # output-safety classifier

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev

# 4. Open http://localhost:5173 (or whatever port Vite reports), or just check the API:
curl http://localhost:8000/api/v1/health
```

Or, from the repo root: `make setup && make dev` runs both. `make eval` ingests the bundled
demo document and runs the full benchmark suite; `make redteam` runs the guardrail attack
corpus; `make test` / `make lint` run both halves' real test and lint suites.

## What's actually in here

- **Ingestion**: Docling (PDF/DOCX/PPTX/images), trafilatura (HTML), plus Markdown/TXT/CSV/EML/
  RTF, an SSRF-guarded URL scraper, and a quality-repair refiner — all real parsers, not stubs.
- **PII vault**: Presidio detection + deterministic HMAC tokenization + Fernet-encrypted vault,
  with an audited reveal endpoint. Nothing downstream of ingestion ever sees raw PII.
- **Retrieval**: 6 chunking strategies, dense (ChromaDB) + sparse (BM25) hybrid search via
  Reciprocal Rank Fusion, cross-encoder reranking, HyDE, MMR/cosine/n-gram dedup.
- **GraphRAG**: spaCy NER + LLM triple extraction, deterministic entity resolution, Louvain
  communities, NetworkX by default with a Neo4j adapter behind the same interface.
- **Agentic RAG**: a real LangGraph state machine (planner/rewriter/retriever/critic/
  synthesizer/verifier/guardian) with bounded retry loops, plus simpler hybrid/graph modes.
- **LLM Council**: opt-in multi-model ensemble — independent answers, anonymized peer review,
  chairman synthesis, a real computed agreement score. Separately, every default (non-council)
  turn goes through a per-query Model Router with a real latency-budget fallback.
- **Guardrails**: regex heuristics + a prompt-injection classifier + Llama Guard, an audit log,
  and a 42-attack/15-benign red-team suite with a published, re-measured block rate.
- **Evaluation**: synthetic eval-set generation from a document's own chunks, textbook
  retrieval metrics, LLM-judge generation scoring, a profiler + 5-candidate chunking tournament
  (the "Advisor"), and a full benchmark runner with hard production gates.
- **Frontend**: a real app (not a mock) — upload a document and watch it ingest through a
  trace-driven Stepper, chat with real citations/quality scores/model routing, a Dashboard with
  the Advisor's Accept/Ignore flow, an Architecture tab animated by a live `/ws/trace`
  WebSocket, a force-directed Knowledge Graph view, and a Guardrails audit log + red-team
  trigger — plus a landing page.

Every number any of these screens show is either read straight off a real backend response or
computed from one — see docs/DECISIONS.md for the specific "Estimated vs. Verified" labeling
rule and several real, non-cherry-picked benchmark results it records along the way.

## Hardware tiers

| Tier | RAM | LLMs | Council execution |
|---|---|---|---|
| `8gb` | 8 GB | smaller/fewer models recommended | runs members/reviewers sequentially |
| `16gb` (default) | 16 GB+ | `llama3.2:3b` + `qwen2.5:7b-instruct` + `gemma2:2b` | runs members/reviewers concurrently |

Set `HARDWARE_TIER` in `.env` — `app/council/service.py` reads it directly to decide
sequential-vs-parallel execution for the council and model router.

## Stack

Backend: FastAPI, LangGraph, LiteLLM (Ollama by default; Groq/Gemini optional), sentence-
transformers, bm25s, ChromaDB (Qdrant optional), NetworkX (Neo4j optional), spaCy, Docling,
Presidio, SQLite + SQLAlchemy async. Frontend: Vite, React 19, TypeScript, Tailwind v4, Framer
Motion, GSAP (installed, not yet used — see docs/VALIDATION_REPORT.md), @xyflow/react,
react-force-graph-2d, Zustand, React Router, Playwright. Full rationale for notable choices
lives in [docs/DECISIONS.md](docs/DECISIONS.md).

## Repo layout

```
backend/app/     api, core, ingestion, privacy, chunking, embeddings, stores, retrieval,
                 graphrag, agents, council, guardrails, profiler, evaluation, llm
backend/scripts/ run_redteam.py (make redteam), run_eval.py (make eval)
backend/tests/   pytest suite — real pipelines, real local LLM calls, no mocked backend logic
frontend/src/    pages/ (the 6 app screens + landing), components/ui/ (design system),
                 components/layout/ (app shell), hooks/, lib/api/ (typed client + SSE/WS),
                 store/ (Zustand)
frontend/tests/e2e/  Playwright E2E against a real running backend — see its own README
data/demo/       bundled demo document (data/demo/hr_handbook.md) `make eval` runs against
docs/            ARCHITECTURE, API, USAGE, GUARDRAILS, EVALUATION, BENCHMARKS, UI_MOTION,
                 DECISIONS, VALIDATION_REPORT
```

## Troubleshooting

- **"Ollama unreachable" in `/health`.** Install from [ollama.com](https://ollama.com) and make
  sure it's running (`ollama serve`, or just open the app) — `OLLAMA_BASE_URL` in `.env` defaults
  to `http://localhost:11434`.
- **`uv sync` can't find Python 3.11.** `uv python install 3.11` fetches it; no system Python
  change needed.
- **A chat/council/advisor call is slow or times out.** Everything LLM-backed in this project
  runs against your local Ollama models by default — the first call to a given model pays a
  cold-load cost, and the agentic/council modes make several sequential model calls per turn.
  Measured, real latencies (not estimates) are in docs/DECISIONS.md and docs/BENCHMARKS.md.
- **Dev DB schema errors after pulling new code.** `Base.metadata.create_all()` only adds new
  tables, it never alters existing ones. Delete `backend/var/data/` (dev data is disposable)
  and restart — this comes up any time a column was added to an existing table; see
  docs/DECISIONS.md for the recurring note on this.
