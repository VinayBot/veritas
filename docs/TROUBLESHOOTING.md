# Troubleshooting

## Incident: upload hangs forever on "Ingesting..."

**Symptom.** Uploading a document (reported with `data/demo/northwind_remote_work_travel_policy.pdf`,
one page) left the UI showing "Ingesting..." indefinitely. No error, no progress, no recovery —
the only way out was reloading the page, which lost the upload entirely.

### Root cause

`POST /documents/upload` ran the *entire* pipeline — parse, refine, PII-mask, chunk, embed,
index, extract the graph, profile, and run the chunking-strategy advisor — synchronously, inside
one HTTP request, with no timeout anywhere in that chain.

Four of those stages lazily load a model on first use (`@lru_cache`-wrapped getters): Docling's
layout+table models, the sentence-transformers embedder, Presidio's PII detector (spaCy), and the
cross-encoder reranker. On a machine where none of those models are cached yet, "parse" and
"embed" each silently block on a multi-minute download — with no progress event, no timeout, and
nothing to distinguish "slow" from "stuck." The frontend had nothing to show but the one spinner
it started at upload time.

**Measured, not assumed.** Isolating the model cache (`HF_HOME` pointed at an empty directory) and
re-running the exact same upload gave:

| Stage | What loaded | Time |
|---|---|---|
| parse | `docling-layout-heron` | 56.44s |
| parse | `docling-models` (TableFormer) | 111.32s |
| embed | sentence-transformers embedder | (remainder) |
| **Total** | | **248.91s** |

Nearly 4.5 minutes, with the HTTP connection held open the entire time and the UI showing nothing
but the initial spinner. On a slower connection, this does not just feel like a hang — it can
become one if the request times out upstream (proxy, browser) before the download finishes, with
no way to retry short of re-uploading from scratch.

**Ruled out, with evidence, not assumption:**

- *Ollama unreachable* — pointed `OLLAMA_BASE_URL` at an unreachable port and re-ran. Fails fast
  (connection refused) in ~15s and degrades gracefully (chat still works without the LLM-dependent
  extras). Not the cause of a hang.
- *Corrupt / 0-byte / password-protected PDFs* — all three fail in under a second with a 500. Not
  a hang — though the error message itself was a real, separate hardening gap (see below).
- *Chroma/Qdrant locks, upload size limits, missing system deps* — none reproduced; the vector
  store write succeeded immediately in every run.

### The fix

**1. A persisted job state machine**, not a single blocking call. `POST /documents/upload` now
saves the file, creates a `Document` row (`status="queued"`), launches the pipeline as a detached
background task (`asyncio.ensure_future` + a module-level strong-reference set, since `asyncio`
only keeps a *weak* reference to a bare `create_task` — see `app/ingestion/service.py`), and
returns immediately. `GET /api/v1/documents/{id}` reports `status` (`queued` → `running` →
`ready`/`failed`/`cancelled`), `current_stage`, and on failure `error_stage` + `error_message`.

**2. Every stage has a timeout.** `STAGE_TIMEOUTS` in `app/ingestion/service.py` bounds parse
(300s — generous enough for the measured cold-cache case above), embed (180s), graph/advisor
(300s, LLM-bound), and every other stage. A `TimeoutError` becomes a clear message naming the
stage and suggesting a retry, instead of an open-ended hang.

**3. Critical path first, enrichment after.** Parse → refine → PII-mask → chunk → embed → index
marks the document `ready` — chat works as soon as this finishes. Graph extraction, profiling,
and the chunking advisor run afterward as a separate background phase (`enrichment_status`,
independently `running`/`done`/`failed`/`cancelled`) that can never block or fail the document's
usability for chat.

**4. Startup preflight.** `app/core/preflight.py` warms every lazy model (embedder, PII detector,
Docling, reranker) and checks Ollama reachability + a real vector-store write — concurrently, at
server boot, non-blocking (`asyncio.create_task`, never awaited by the lifespan). This moves the
248-second cold-cache cost from a user's first upload to the server's startup, where it belongs.
Results are cached and served from `GET /api/v1/health`'s `preflight` field; the frontend shows a
banner if anything comes back missing or unreachable. Run `make models` to pay this cost
standalone (CI, Docker image bake, or just once after `make setup`), independent of starting the
server at all.

**5. Startup reconciliation.** A `Document` stuck `queued`/`running` from a previous process life
(the in-memory task died with the old process) is marked `failed` with "interrupted by restart" —
instead of spinning forever with nothing left to ever update it.

**6. Frontend**: the Workspace's ingestion UI now polls the real `current_stage`/`status`/elapsed
time instead of assuming one shot of the old synchronous call. A stage running past 20 seconds
shows "Taking longer than expected" with the stage name. A failed job shows the real error message
with **Retry** (`POST /documents/{id}/retry`) and **Cancel** (`POST /documents/{id}/cancel`)
actions. If the trace WebSocket drops, the UI reconnects with backoff and falls back to polling
`GET /documents/{id}` every 2 seconds so progress is never silently lost.

**7. Hardened error messages.** Docling's own `UnsupportedFormatError`/parse failures used to leak
an internal content-hash key (`"docling-parse could not load document e3b0c4..."`). Messages
surfaced to the API/UI are now stage-specific and human-readable instead of passing the
library's raw exception text through unexamined.

**8. Fast, synchronous rejection for unsupported formats.** Splitting ingestion into a background
job initially introduced a regression: an unsupported extension (e.g. `.exe`) would get queued as
a job and only fail asynchronously, instead of the original instant `422`. Fixed by checking the
extension against the parser registry synchronously in `ingest_upload()`, before the document row
or background task is even created — fast failures stay fast.

### How to self-diagnose this class of issue

1. **Check `GET /api/v1/health`'s `preflight` field first.** If any check is `"ok": false`, that's
   almost always the actual cause of a slow/stuck ingestion, not something later in the pipeline.
2. **Check `GET /api/v1/documents/{id}`.** `current_stage` tells you exactly where the job is;
   `status="failed"` always comes with `error_stage` + `error_message`, never a silent stall.
3. **A document stuck in `queued`/`running` across a backend restart** will show up as `failed`
   with "interrupted by restart" the next time you check it — re-upload rather than waiting.
4. **First upload after a fresh environment (`make setup` with no prior model cache) is expected
   to be slow** unless you've run `make models` first — this is the ~4-minute cost described
   above, now visible in `/health` and the startup logs instead of hidden inside a request.
5. **Backend logs** carry a structured line per stage (`"Ingestion stage %r failed for document
   %s: %s"`, timed trace events for `upload_received`/`parse`/`refine`/`pii_detect`/`chunk`/
   `embed`/`index_bm25`/`index_vector`/`graph_extract`/`profile`/`advise`) — if a stage never logs
   a completion, it's still genuinely running or it's the one that will time out next.

## Incident: chat answers were doubled and sometimes wrong ("Bug A" / "Bug B")

**Symptom.** After uploading a document and asking a question, no real answer arrived — the UI
showed `"I don't have enough reliably-supported information to answer that."`, and streamed text
was visibly doubled: `"I don't have enough reliably-supported I don't have enough
reliably-supported information to answer information to answer that.that."`

### Bug A — every streamed token applied twice

**Root cause, reproduced live, not guessed.** `WorkspacePage`'s `setMessages` updater did:

```ts
setMessages((prev) => {
  const next = [...prev]
  const last = next[next.length - 1]      // same object `prev` still points to —
  last.content += evt.data                // the outer [...prev] only copies the array,
  return next                             // never the message objects inside it
})
```

`frontend/src/main.tsx` wraps the app in `<StrictMode>`, which deliberately **double-invokes** a
functional `setState` updater in development, specifically to catch impure updaters like this
one. React discards the first invocation's *return value* — but the mutation (`last.content +=
evt.data`) had already happened on the shared object, so the second, "real" invocation read
`last.content` *after* the first invocation's append and appended the same delta again. Every
single chat answer was silently doubled this way, for every field the updater touched
(citations, agent_steps, quality, routing, reportId, errored), not just tokens.

**Fix**: derive a new message object instead of mutating the old one
(`frontend/src/pages/workspace-page.tsx`) — `{...last}` plus a plain reassignment, never `+=` on
a field read from `prev`. A pure updater is idempotent under double-invocation by construction:
both calls compute the same `last.content + evt.data` from the same unmutated `last`.

### Bug B — a correct, well-evidenced answer was abstained anyway

**Root cause, reproduced live.** Asked "How many days per week can employees work remotely?"
against a document whose top-ranked, high-scoring retrieved chunk says *"Employees may work
remotely for up to three days per week..."* verbatim — retrieval was measurably correct
(`dense_score: 0.78`, `bm25_score: 4.84`, rank 1) and the Critic agreed the evidence was
sufficient. The Synthesizer drafted a correct answer. The Verifier (`app/agents/verifier.py`)
then rejected it, calling the raw model directly to isolate the fault:

```
RAW OUTPUT: '["Home office stipends of a fixed annual amount are available to any employee
who works remotely at least one day per week on a regular basis."]'
```

That sentence is copied verbatim from the *context* — it was never part of the drafted *answer*
at all. The local 3B verifier model, asked to list unsupported sentences **in the answer**,
instead echoed an unrelated sentence from the context: syntactically valid JSON, semantically
not a real finding (a context sentence trivially doesn't need to be "supported by the context").
Two rounds of this (initial check, then again after a revision the Synthesizer had no real
defect to fix) exhausted the revise budget and forced an abstain on a fully correct answer.

**Fix**: `app/agents/verifier.py` now discards any claimed "unsupported sentence" that doesn't
actually appear in the answer (`_is_claim_grounded_in_answer` — exact match after whitespace
normalization, or ≥70% word overlap to tolerate minor punctuation/quoting drift) before deciding
to revise or abstain. A claim about the answer that isn't *in* the answer is a model slip, not
evidence — discarding it is strictly safer than trusting it, since a genuine unsupported claim
is by construction copied from the answer and passes the grounding check easily.

**Verified both fixes together, live, after the fix**: the same question now streams the
correct answer cleanly, once, with a real citation and `faithfulness: 0.8` — see
`frontend/tests/e2e/chat.spec.ts` for the permanent regression coverage (doubled-text detection
across three real scenarios: a grounded factual answer, a blocked injection, and a genuine
abstain) and `backend/tests/test_agents_verifier.py` for a deterministic unit reproduction of
the exact bad model output above.
   a completion, it's still genuinely running or it's the one that will time out next.
