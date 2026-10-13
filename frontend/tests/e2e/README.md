# E2E tests

Real Playwright tests against a real backend — no mocked API responses. Every assertion here
is checking genuine data: a document actually ingested, a real chat answer, a real tournament
result.

## Running

1. Start the backend with Ollama up: `make backend-dev` (or `make dev` for both) from the repo
   root. The configured answer model (`DEFAULT_LLM_MODEL`) and `llama-guard3:1b` must be pulled.
2. From `frontend/`: `npx playwright test` (it starts the Vite dev server itself).

The full flow test ingests a real document (which runs the real profiler/advisor tournament)
and sends a real chat message, so a single run takes a few minutes — this is the honest cost
of testing against real local-LLM inference rather than a mock, consistent with the rest of
this project's testing philosophy (see ../../docs/DECISIONS.md).

Not covered here (see docs/VALIDATION_REPORT.md for the full, honest list): triggering the
Evaluation tab's actual benchmark run (minutes on its own), the red-team suite button, and the
Dashboard's Accept/Ignore buttons (both real and working — see tests/e2e/smoke.spec.ts's
manual verification notes in docs/DECISIONS.md — just not re-exercised by this automated test
to keep it from taking 10+ minutes on every run).
