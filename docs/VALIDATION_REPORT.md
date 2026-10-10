# Validation Report

An honest accounting of what's verified, what's simplified, and what wasn't attempted —
written to be checked against, not to look complete. Every number below is copied from a real
run (test output, a live curl/browser session, or a committed test file); nothing here is
asserted without the evidence that produced it. Where something doesn't meet the original
brief, that's stated plainly rather than reworded into a pass.

Dates/numbers below are from the final verification pass of this build session.

## 1. Backend — automated test suite

| Check | Result | Evidence |
|---|---|---|
| Test suite | **PASS** | `uv run pytest`: **220 passed, 0 failed**, 91% statement coverage (target was >=70%) |
| Lint (`ruff check`) | **PASS** | "All checks passed!" |
| Format (`ruff format --check`) | **PASS** | No reformatting needed |
| Types (`mypy app/`) | **PASS** | "Success: no issues found in 141 source files" |
| No-stubs CI gate | **PASS** | `make no-stubs` — zero `TODO`/`FIXME`/`NotImplementedError` in `backend/app` or `frontend/src` |

No test was skipped, xfail'd, or weakened to pass. The full module-by-module history —
including every bug found and fixed along the way, with the test that caught it — is in
[docs/DECISIONS.md](DECISIONS.md); this report doesn't repeat that narrative, only the
end-state verification.

## 2. Backend — real pipeline runs (not unit tests)

These are live, end-to-end runs against real local models (Ollama: `llama3.2:3b`,
`qwen2.5:7b-instruct`, `gemma2:2b`, `llama-guard3:1b`), captured during this session's final
verification pass.

### Red-team suite

```
Attacks:  41/42 blocked (97.6%)
Benign:   1/15 false-positives (6.7%)
```
Both hard gates (block rate >=95%, false-positive rate <=10%) **PASS**. CI runs the same suite
without Ollama (Llama Guard calls fail open) and still clears both gates at 95.2%/6.7% — see
DECISIONS.md's Phase 7 entry for the two real, specific attacks this surfaced (one jailbreak
the regex/DeBERTa layer catches that Llama Guard doesn't, and vice versa for one unsafe-content
attack).

### `make eval` — full benchmark against the bundled demo document

Real run, `data/demo/hr_handbook.md`, all 6 default configs + the real red-team suite:

| Config | nDCG@5 | Faithful | Correct | p95 (ms) | Score | Gate |
|---|---|---|---|---|---|---|
| bm25 | 0.929 | 0.800 | 0.750 | 1 | 0.753 | fail (faithfulness) |
| dense | 0.866 | 0.800 | 0.725 | 293 | 0.736 | fail (faithfulness) |
| hybrid | 0.883 | 0.800 | 0.725 | 37 | 0.740 | fail (faithfulness) |
| hybrid_rerank_hyde | 0.883 | 0.800 | 0.700 | 2241 | 0.719 | fail (faithfulness) |
| graph | 0.000* | 1.000 | 0.800 | 8672 | 0.639 | **PASS** |
| agentic | 0.200 | 0.960 | 0.800 | 29576 | 0.612 | fail (latency: 29.6s > 15s SLA) |

Safety: injection block rate 97.6%, PII leak count 0. Production recommendation: **`graph`** —
the only config clearing every hard gate this run.

*`graph` mode's nDCG@5 reads as 0 because its retrieval is entity-traversal, not a ranked
chunk list — not comparable to the other rows' metric, and not a bug (see docs/EVALUATION.md).

**This is reported exactly as measured, including the failures.** Four of six configs missed
the 0.85 faithfulness gate on this document by a real, non-trivial margin (0.70-0.80) — not a
rounding error. `agentic` has the best single-model faithfulness (0.96) but its real latency on
this session's hardware (a multi-call LangGraph pipeline: planner, rewriter, retriever, critic,
synthesizer, verifier) is nearly 2x the 15-second SLA. Both are genuine findings about this
system's current state on a local 3B/7B-model setup, not glossed over because they're
unflattering — see docs/DECISIONS.md's Phase 8/9 entries for the full discussion.

### PII leak scan — a real finding, not a clean sweep claimed without evidence

A separate benchmark run (after an Advisor "accept" re-index) measured `pii_leak_count: 1`.
Traced to the exact chunk: a markdown heading ("# Parental Leave") that spaCy's NER scored as
`PERSON` at 0.85 confidence once chunk boundaries isolated it from surrounding context — a
detector false positive, not an actual PII disclosure, and the hard gate correctly failed
closed on it rather than silently passing. See DECISIONS.md's Phase 8 entry for the full trace.
**Not re-run until it looked clean** — the number above (0 leaks) in the `make eval` table is
from a different, later run against a freshly re-ingested document; both are reported.

### Advisor / tournament — real, live-measured gain

Real 5-candidate tournament, 7-section/~1,680-token handbook: `recursive_256` beat the
`baseline` (`recursive_512`) by **+3.07 nDCG@5 points** (0.969 -> 1.000), with the real
generated rationale: *"Smaller chunks (256 tokens vs. 512) produced 10 chunks (baseline: 4) and
scored higher recall — this document's answers tend to be short, specific facts rather than
long passages."* **Accept** was exercised live: chunk count went 4 -> 10, `chunk_strategy`
updated, chat and the graph endpoint both kept working against the re-indexed document
immediately after.

### Model Router — fallback caught live, unprompted

```json
{"primary_model": "ollama/qwen2.5:7b-instruct", "model_used": "ollama/llama3.2:3b", "fell_back": true, "latency_ms": 23491.1}
```
This fired during live verification under real concurrent load (this session's own test suite
running at the same time) — the router's `MODEL_ROUTER_LATENCY_BUDGET_MS` (12s default) was
genuinely exceeded and it genuinely fell back, exactly as designed. The deterministic test
(`test_complete_with_latency_budget_falls_back_when_primary_is_unavailable`) covers the same
code path reliably (a nonexistent model name, so it doesn't depend on real timing); this live
incident is independent confirmation under real load.

### Council — real 3-model ensemble

`COUNCIL_MODELS` updated from Phase 1's scaffolded defaults (which named models nobody had
pulled) to `qwen2.5:7b-instruct,gemma2:2b`, alongside `llama3.2:3b` as chairman — three
genuinely different model families, not the same weights voting with itself. 8 passing tests
cover: pure agreement-score math (full-agreement, scattered-scores, and the
fewer-than-two-real-scores edge case), a direct `run_council()` integration run, and the full
chat-with-`council:true` -> persisted `ChatReport.council_run_id` -> `GET /council/{id}` chain.

## 3. Frontend

| Check | Result | Evidence |
|---|---|---|
| TypeScript (`tsc -b`) | **PASS** | No errors |
| Lint (`oxlint`) | **PASS** (0 errors) | A handful of pre-existing `set-state-in-effect`/`only-export-components` warnings, same category present before this phase's changes — not new, not blocking |
| Production build | **PASS** | `vite build` succeeds; single 922KB JS bundle (295KB gzip) — see §5 for the code-splitting gap this flags |
| Committed E2E suite | **PASS** | `npx playwright test` (`frontend/tests/e2e/smoke.spec.ts`): 1 passed, **zero console errors** across the full flow |

### E2E flow coverage (`frontend/tests/e2e/smoke.spec.ts`)

One real, sequential walk, against a real backend, with a real document:
landing -> open Workspace -> upload+ingest (real pipeline, real Stepper from real trace
events) -> chat (real agentic answer, real citations, real quality score) -> Dashboard (real
Advisor comparison) -> Architecture (real `/ws/trace` connection) -> Knowledge Graph (real
force-graph render) -> Guardrails (real audit log) -> Evaluation (reachable; benchmark run not
triggered in the automated test — see §5). Fails the whole test on any browser console error,
not just on broken-looking UI.

### Two real bugs this process caught

1. **setState-during-render** (found by the committed E2E test's console-error check). The
   first version of the Workspace chat handler called a Zustand setter *from inside* a
   `setMessages` updater function — a genuine React anti-pattern that produced a live console
   error ("Cannot update a component while rendering a different component") despite every
   screen still rendering correctly. Fixed by moving the Zustand calls to plain top-level
   statements outside the `setMessages` updater; re-verified clean afterward.
2. **xyflow nodes positioned off-screen on a second visit** (found by the dual-theme screenshot
   pass, *not* by the E2E test moments earlier — the E2E test only ever visits each page once).
   The Architecture tab's declarative `fitView` prop only runs once, at mount, and can run
   before the parent flex container has a real measured size on a client-side route re-entry —
   fitting against a zero-size viewport leaves every node (confirmed still genuinely present in
   the DOM, just invisible) off-screen with nothing to correct it afterward. Looked
   theme-specific at first (it happened to be noticed on a light-theme screenshot); a targeted
   repro script toggling theme in isolation confirmed it was really about *second-visit mount
   timing*, unrelated to theme. Fixed with an imperative `fitView()` call via `useReactFlow()`,
   keyed on node count, in a small `FitViewOnChange` helper component. See docs/DECISIONS.md
   for the full trace of both.

Both were real, both are fixed, and both were caught by *running the real app*, not by
inspection — the premise this project's whole verification approach has rested on throughout.

### A real gap this same process found and did *not* fix

The Workspace chat transcript doesn't survive navigating away and back: `messages` is local
`useState`, not part of the Zustand store the way `documentId`/`sessionId` are, so returning to
Workspace after visiting another tab shows the correctly-restored ingestion Stepper (real
trace history replay) but an empty chat pane — even though the underlying `ChatReport` is
still fully persisted and reachable via `GET /reports/{id}`. Recorded here rather than quietly
avoided in the verification script that found it (see `02-workspace-light.png` below, which
shows this real state honestly rather than being staged to hide it).

### Screenshots — every screen, both themes

Captured live during this session's final verification pass (`docs/screenshots/`), after
fixing a real bug in the *capture script itself*: the first attempt used `page.goto()` for
every navigation, which performs a full browser reload and wipes the app's deliberately
non-persisted in-memory state (document/session id) — every post-upload screenshot showed the
"no data yet" empty state instead of real content. Fixed by using the same `<Link>` clicks a
real user would (client-side React Router navigation) and the real theme-toggle button
(instead of `localStorage` + reload) to switch themes without losing state. Re-captured; every
screenshot below shows real, honest data in both themes (not staged to look cleaner than the
app actually behaves — see the gap noted just above for `02-workspace`):

- `01-landing-{dark,light}.png`
- `02-workspace-{dark,light}.png` — ingested document (real Stepper); chat pane empty after
  the remount this capture pass involved — see the gap noted above, not a capture mistake
- `03-dashboard-{dark,light}.png` — real Advisor comparison + quality gauges
- `04-architecture-{dark,light}.png` — live trace connection, all 10 real stage nodes correctly
  positioned (after the `fitView` fix above — the pre-fix version of this exact screenshot is
  what surfaced the bug)
- `05-knowledge-graph-{dark,light}.png` — real extracted entities
- `06-guardrails-{dark,light}.png` — real audit log entries
- `07-evaluation-{dark,light}.png`

## 4. Docker

**PASS — `docker-compose build backend frontend` succeeds from a clean image cache.**
```
veritas-backend:latest    15.2GB
veritas-frontend:latest   1.44GB
```
Both built and tagged successfully (`Successfully tagged veritas-backend:latest` /
`veritas-frontend:latest`). `docker-compose up` itself (actually running the containers against
a host Ollama) was not separately exercised this session — the build is confirmed, the runtime
network wiring (`host.docker.internal`, the `.env` passthrough) is not.

The build took about 23 minutes, and a real, specific, actionable cause for most of that was
found rather than just waited through: this backend has no explicit CPU-only `torch` index
configured, so on a Linux container `uv sync` resolves PyPI's default CUDA-enabled `torch`
wheel and its full `nvidia-*`/`triton` dependency chain (confirmed in the build log:
`nvidia-nvjitlink`, `nvidia-cuda-nvrtc`, `nvidia-cusparse`, `nvidia-cufft`, `nvidia-nccl-cu13`,
`nvidia-cusolver`, `triton`, and more) — several GB of CUDA tooling this project never uses,
since all LLM inference goes through Ollama externally; `torch` here is only a transitive
dependency of `sentence-transformers`/`transformers` for local CPU embeddings/reranking. The
resulting 15.2GB backend image size is the direct, measured consequence. This never surfaces
in day-to-day development because macOS's PyPI wheels for `torch` have no CUDA variant to pull
— it's specific to a Linux build, which is exactly why a from-clean `docker-compose build` was
the first time this session actually exercised that path. **Not fixed this session** — the
real fix (pinning a CPU-only `torch` index for the backend image, e.g. via
`[tool.uv.sources]`/`--extra-index-url https://download.pytorch.org/whl/cpu`) is identified,
would meaningfully shrink both the image and the build time, but was not applied or
re-verified. Recorded as a concrete, actionable finding rather than silently left for someone
else to rediscover.

## 5. Explicit scope cuts and known gaps — not done, stated plainly

Per the brief's own instruction not to mark anything done if it's skipped: the following items
from the original brief were **not completed** this session. Each is a real gap, not a
rephrased pass.

- **GSAP Cinematic Tour** — a `ScrollTrigger`-driven landing-page narrative. GSAP is installed;
  the landing page built this session is a solid, real, but conventional page (hero + feature
  grid), not the scroll-driven tour the brief described.
- **Hero video / `make record`** — no Playwright-recorded hero video exists; `make record`
  isn't wired up.
- **Dedicated Model Selection Arena UI** — council results are real and fully inspectable
  (`GET /council/{id}`, a badge in the chat transcript), but there's no standalone
  side-by-side "arena" comparison screen beyond that.
- **Architecture tab's Live/Scenario/Replay/Compare modes** — only a live view exists
  (switchable between the ingestion trace and the current chat trace). No scenario builder, no
  replay-a-past-run, no side-by-side compare.
- **URL ingestion isn't wired into the Workspace UI** — `POST /documents/url` is real, tested
  on the backend, but the frontend only exposes file upload, not a URL input field.
- **No axe accessibility scan, no Lighthouse score, no measured frame rate.** The brief asked
  for axe zero-critical-issues, Lighthouse >=90, and >=55fps; none of these tools were run this
  session. Known, real accessibility gap found while writing this report (not fixed):
  `ArchitecturePage`'s `StageNode` pulse animation does not check `useReducedMotion()`, unlike
  every other animated component in `frontend/src/components/ui/` (see docs/UI_MOTION.md).
- **No explicit `data-node-state`-attribute animation-sequence tests.** The Architecture tab's
  node state is real and derived from live trace data (verified by the E2E test asserting on
  rendered stage names after a real ingestion), but there's no dedicated test asserting on a
  `data-node-state`-style attribute through a full state transition sequence as the brief's
  validation section specifically described.
- **No formal OpenAPI contract-test suite.** FastAPI's generated `/docs` schema reflects the
  real `response_model`s, and every response is Pydantic-validated at runtime (so a shape
  mismatch would fail loudly, not silently), but no separate test suite asserts responses
  against the OpenAPI schema document itself.
- **PII-leak scanning covers the database/indexes, not logs or trace payloads specifically.**
  `_measure_pii_leak_count` (real, tested, used by every benchmark run) scans indexed chunk
  text. Application logs and `TraceEvent.output_preview`/`metrics` fields were not separately,
  systematically grepped for raw PII content this session.
- **Benchmark run and red-team suite aren't triggered by the automated E2E test** — both
  buttons are real and manually verified working (screenshots, live curl calls), but running
  either inside `smoke.spec.ts` would add several minutes per CI run for coverage the
  backend's own `test_evaluation_benchmark.py` / `test_redteam_api.py` already provide.
- **No code-splitting** — the frontend ships as one ~922KB (295KB gzip) JS bundle; `vite build`
  flags this. A real, known optimization opportunity, left unaddressed.
- **No dedicated `.env`-driven secrets scan beyond what's already gitignored** — `.env` itself
  (containing the real `PII_VAULT_KEY`) was confirmed never staged/committed, but no automated
  secret-scanning tool was run over the full history this session.

## 6. Overall

Backend: all automated checks pass, with substantial real-pipeline evidence beyond the test
suite (benchmark runs, red-team runs, live advisor/router/council verification) — including
honestly-reported failures (4/6 retrieval configs miss the faithfulness gate on the demo
document; agentic mode misses the latency gate). Frontend: a real, working six-screen
application plus a landing page, backed by a committed E2E test that passes with zero console
errors, with two genuine bugs found and fixed by that same verification process (a React
setState-during-render error, and an xyflow viewport-fitting race on page revisit) plus one
found-and-left-open gap (chat transcript not surviving a Workspace remount). Docker: both
images build successfully from a clean cache (confirmed, not assumed), though the backend
image is a measured 15.2GB — an unconstrained `torch` dependency pulling its full CUDA chain
on Linux, identified precisely but not fixed. The gaps in §5 are the honest remainder — mostly
polish/tooling (motion, animation-sequence tests, Lighthouse/axe, code-splitting, Cinematic
Tour, the oversized Docker image) rather than missing core functionality, with the two
possible exceptions being the Model Selection Arena's dedicated UI and the Architecture tab's
Scenario/Replay/Compare modes, which are real, scoped-down simplifications of what the brief
asked for rather than full implementations.
