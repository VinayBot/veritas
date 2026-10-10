# Usage

A walkthrough of the running app — see [docs/API.md](API.md) if you want the underlying
endpoints instead of the UI.

## 1. Upload or ingest a document

Open the **Workspace** tab. Drop a file (PDF, DOCX, PPTX, HTML, Markdown, TXT, CSV, EML, RTF)
or click to browse. Ingestion runs synchronously and the Stepper above the chat box fills in
live, stage by stage, from real backend trace events — Upload, Parse, Refine, PII Vault,
Chunk, Embed, Index, Graph, Profile, Advisor. A larger document (roughly a page or more) will
also trigger a real chunking tournament during that last "Advisor" stage; a one- or two-chunk
document won't (see docs/DECISIONS.md for the exact threshold and why).

URL ingestion (`POST /documents/url`) isn't wired into the Workspace UI yet — see
docs/VALIDATION_REPORT.md.

## 2. Chat with it

Once the document shows `ready`, ask a question. Three modes (chips above the input):

- **agentic** (default) — the full LangGraph pipeline: plans, retrieves, critiques its own
  retrieval, synthesizes, verifies its own claims against the context.
- **hybrid** — a single hybrid-search call + one synthesis call. Faster, simpler.
- **graph** — retrieves via graph traversal instead of vector/keyword search.

Toggle **Council** to replace single-model synthesis with a real multi-model vote (every
model in `COUNCIL_MODELS` answers, peer-reviews anonymously, a chairman model synthesizes the
final answer) — slower, and surfaces a `council run <id>` badge you can look up in full via
`GET /api/v1/council/{id}`. Toggle **Reveal PII** to allow the output guardrail to show
previously-masked values this session is authorized to reveal.

Each answer carries: its citations (hover for the source text), a quality badge (`estimated:
confidence NN%` — click for the full faithfulness/relevancy/citation-validity breakdown), and
either a routing badge (which model actually answered, and whether it fell back) or the
council badge. Click the step count to expand the full agent trace for that turn.

## 3. Dashboard

Shows the current document's **Advisor** recommendation: a real tournament result
(Baseline vs. Suggested configs, their measured nDCG/faithfulness/latency, the rationale tied
to those numbers, and the suggested RAG mode). If no recommendation exists yet (document too
small, or never run), click **Run advisor now**. **Accept** re-chunks/re-embeds/re-indexes the
document with the suggested config for real; **Ignore** just records the decision. Below that,
the most recent chat turn's quality scores as gauges.

## 4. Architecture

A live diagram of the real pipeline, switchable between the **ingestion** trace (this
document's upload) and the **chat** trace (the current session's agentic/hybrid/graph run).
Every node's color and pulse comes from a real `TraceEvent` over `/ws/trace/{session_id}` —
click a node for its real duration/output/metrics in a side panel.

## 5. Knowledge Graph

The entities and relations GraphRAG extracted from the current document, force-laid-out and
colored by detected community. Search to run a real graph traversal from matching entities
instead of showing the whole graph; click a node for its mentions and document coverage.

## 6. Evaluation

**Generate dataset** builds a fresh synthetic eval set from the document's own chunks.
**Run benchmark** scores every retrieval/agent config against a fresh eval set plus the real
red-team suite, and shows the same table `make eval`/`docs/BENCHMARKS.md` would — this is a
genuinely slow, real operation (several minutes), not a quick mock call.

## 7. Guardrails

**Run red-team suite** fires the real 42-attack/15-benign corpus at the live input guardrail
and reports the real block rate and false-positive rate. The audit log below shows every real
guardrail decision (allow or block, every layer) across every chat turn so far.
