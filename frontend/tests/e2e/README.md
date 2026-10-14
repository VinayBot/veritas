# End-to-end tests

32 Playwright tests that drive the real UI against the real backend and real local models; no
API response is mocked.

| Spec | What it covers |
|---|---|
| `ingestion.spec.ts` | Upload stages in order, clear errors for corrupt and empty files, cancel and retry, readiness without the trace WebSocket |
| `app.spec.ts` | Three tabs, quick vs Deep answers, history across reloads, per-document strategy measurement and recommendation, comparisons, an evaluation run, the knowledge graph, reduced motion |
| `architecture.spec.ts` | Diagram from the backend payload, health probes, node drawer by keyboard, exports, pulses only from real trace events |
| `everything.spec.ts` | Every control: starters, stopping an answer, model and strategy switching, building an index on demand, document switcher, command palette, Evaluation views, red-team run |

## Running

1. Start the backend with Ollama running: `make backend-dev` (or `make dev` for both) from the
   repo root. `llama3.2:3b` and `llama-guard3:1b` must be pulled.
2. From `frontend/`: `npx playwright test` (it starts the Vite dev server itself).

A full run takes about 15 minutes on a 16 GB laptop, most of it real model inference.
