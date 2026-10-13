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

## Incident: "Can a German contractor work remotely without approval?" always abstained

**Symptom.** Against the enriched Northwind fixture (4 real chunks, ~1370+ tokens), this golden
question always abstained in agentic mode, even though the top-ranked retrieved chunk states
the answer explicitly (an international-contractor exception, naming Germany specifically, with
the approver's name masked as `<PERSON_6cc6eb>`). First hypothesis — the model choking on the
PII token — was wrong (a prompt clause explaining the token didn't change the outcome) and led
to live-reproducing five independent, compounding bugs on the real agentic path, each confirmed
by calling the actual pipeline functions directly and inspecting raw model output before fixing
anything.

### Bug C — `build_numbered_context` silently truncated every chunk to 500 characters

`app/agents/context_utils.py` built the Synthesizer's and Verifier's context as
`h["text"][:500]`. Real chunks target 512 *tokens* (`BASELINE_SIZE`, `app/chunking/registry.py`)
— roughly 2000+ characters of English prose — so this cut off after only the chunk's opening
paragraph. The sentence naming Germany started at character 1066; the model never saw it.
Confirmed by calling the Synthesizer's exact prompt-plus-system-message directly: with the
500-char slice, the model correctly reported "it does not specify a nationality requirement" —
a true statement about the truncated text it was actually given. **Fix**: pass the full chunk
text; chunks are already bounded by the chunker's own token budget, so slicing again here was
redundant as well as wrong.

### Bug D — the Critic averaged relevance scores instead of taking the best one

`app/agents/critic.py`'s corrective-RAG check computed `avg_score = sum(scores) / len(scores)`
over the top-5 retrieved chunks and compared it to `SCORE_THRESHOLD = 0.3`. Reproduced live: the
correct chunk scored **+4.6** on the cross-encoder (a strong match), but the 3 other, genuinely
irrelevant chunks in the same top-5 scored **-8 to -11** — raw cross-encoder logits run far more
negative for "irrelevant" than positive for "relevant" on this model. Averaging let the filler
veto the one excellent match (avg ≈ -5.7), so the Critic judged the evidence insufficient and
burned all 3 rewrite-retry attempts (HyDE, step-back, multi-query) before giving up — on every
attempt, since the same filler chunks came back every time. **Fix**: use the best score in the
top-k, not the mean; a corrective-RAG check should ask "is there at least one good source," not
"is the whole retrieved set uniformly strong" (hybrid retrieval mixing in some noise alongside
the right answer is normal, not a sign of a bad retrieval).

### Bug E — the Critic's own LLM-grading prompt collided with the question's polarity

Even after Bug D, the Critic's second signal — "Can this question be answered using ONLY the
context above? Reply yes or no." — still said "No." given *only* the one perfectly relevant
chunk. Isolated the cause with a controlled comparison: a question whose true answer is
affirmative got "Yes."; the *same* context rephrased as a question whose true answer is
negative/restrictive got "No." — the small grading model was answering the *object-level*
question (there's no approval-free remote work for German contractors) instead of judging
*answerability* (the context clearly states the restriction, so the question plainly can be
answered). Reworking the prompt to ask for `ANSWERABLE`/`UNANSWERABLE` instead of `yes`/`no`
didn't fix it alone — `DEFAULT_LLM_MODEL` (llama3.2:3b) still collapsed "the answer is
restrictive" into "unanswerable." Swapping just this judgment call to
`council_models[0]` (`qwen2.5:7b-instruct` — already the system's designated stronger model,
see `select_primary_model`) got every case right in the same live comparison. **Fix**: reworded
prompt + stronger model for this one call; first-pass answer *generation* is untouched and keeps
the fast complexity-based router.

### Bug F — the same Critic call also truncated its own context to 300 characters

Separately from Bug C (`context_utils.py`), `critic.py`'s own `_llm_grade` built its grading
context as `h["text"][:300]` — an even tighter slice of the same chunk, cutting off before
"International Contractors" for the same underlying reason. Confirmed by dumping the Critic's
exact prompt from a live run: the model was being asked to judge answerability from a context
block that only contained the "Remote Work Eligibility" paragraph. **Fix**: full chunk text,
matching the Bug C fix.

### Bug G — the Verifier flagged a sentence copied almost verbatim from the context

With Bugs C-F fixed, the Synthesizer produced a correct, cited answer — and the Verifier then
flagged one of its two sentences as unsupported, triggering a revision that sometimes still
ended in abstain. Reproduced live with the exact context and answer text: `llama3.2:3b` returned
`'["This includes contractors based in Germany, ...regardless of the terms in their local
contracting agreement."` (a sentence that is a **character-for-character** quote from the
context) as unsupported; `qwen2.5:7b-instruct` correctly returned `[]` on the same input. Fixed
the Verifier's grading call the same way as Bug E (`council_models[0]`) — but a second, *shorter*
version of the same context (missing two unrelated sections that happen to share the real
chunk) did **not** reproduce the failure even on the weak model, meaning the full ~2600-char,
multi-section chunk length specifically was part of what triggered it. Rather than trust either
model's judgment alone for a case this reproducible, `app/agents/verifier.py` also gained
`_is_claim_grounded_in_context`: a claim that is itself a near-verbatim excerpt of the context is
supported *by definition*, independent of what either model concludes — the same shape as the
existing `_is_claim_grounded_in_answer` check (Bug B above), but checked against the context
instead of the answer, and held to a stricter 0.9 word-overlap bar (vs. 0.7) since it overrides a
verdict the model actually reached rather than just screening out a hallucinated finding.

### Bug H — the Synthesizer's revision pass dropped its citation marker

Once Bugs C-G no longer forced a wrongful abstain, the *revised* answer (produced after the
Verifier's first pass flagged something, before Bug G existed) sometimes came back with no `[n]`
marker at all, and once with a bizarre self-contradicting hedge: *"I don't have enough
information to provide a definitive answer. However, [a complete, correct, specific answer]."*
Reproduced 2/2 on `llama3.2:3b`, 0/2 on `qwen2.5:7b-instruct` with the identical revise prompt.
**Fix**: `complete_with_latency_budget` (`app/llm/router.py`) gained a `force_primary_model`
override, and the Synthesizer's revision branch (only the revision branch — first-pass synthesis
keeps the fast complexity-based router) always passes `council_models[0]`, on the reasoning that
*correcting* a flawed answer while preserving its citation is inherently a harder task than a
first-pass answer, regardless of how simple the original query looks.

**Verified live, repeatedly, after all six fixes**: 5 consecutive runs against fresh uploads
(3 exercising the full pipeline fresh, 2 served correctly from the semantic cache) all returned
the correct, cited answer with zero abstains — including runs that needed a revision pass and
runs that didn't. See `backend/tests/test_agents_critic.py`
(`test_critic_with_one_strong_hit_among_weak_filler_is_sufficient`),
`backend/tests/test_agents_verifier.py`
(`test_verifier_accepts_a_multi_clause_sentence_copied_almost_verbatim`,
`test_claim_grounded_in_context_accepts_an_exact_quote`), and `backend/tests/test_model_router.py`
(`test_complete_with_latency_budget_force_primary_model_overrides_the_pick`) for permanent
regression coverage. A separate, lower-severity gap surfaced during this verification and is
*not* fixed by the above: first-pass synthesis (still on the fast default model for simple
queries) occasionally omits its `[1]` marker even when the answer is correct and the Verifier
confirms it's fully supported, which trips the output guardrail's non-blocking
`escalate (missing_citations)` audit flag. The answer still reaches the user correctly either
way; tracked as a follow-up, not folded into this fix.

### Observed but not reproduced: an intermittent Llama Guard output false-positive

While spot-checking the fixes above against other named individuals in the same document, one
run of a different, unrelated question ("Who signs off on the final version of the annual
policy review?") came back as `"I can't provide that response."` — the output guardrail's
`llama_guard_output` block path (`app/guardrails/output.py`), not an abstain. Re-running the
identical question immediately after returned the correct answer (`"...Elena Petrova, Director
of Global Operations."`), and directly classifying three reasonable variants of that same
correct sentence all came back `is_safe=True` — so this didn't reproduce, and the exact text
that got flagged on the one failing run wasn't captured (synthesis runs at `temperature=0.2`, so
the exact wording isn't reproducible after the fact). Logged for awareness rather than
root-caused: this is a different subsystem (output safety classification) from Bugs C-H above,
the project already has one documented Llama Guard false-positive pattern (the S7/`reveal_pii`
case in `docs/DECISIONS.md`), and chasing a non-reproducing intermittent failure without the
triggering text would mean guessing at a fix rather than verifying one.

## Incident: "graph" chat mode found 0 evidence for a question the document clearly answers

**Symptom.** Spot-checking the same golden question in `graph` mode (one of the three valid
chat modes alongside `agentic`/`hybrid`) returned an abstain with `"retriever": "Graph retrieval
found 0 piece(s) of evidence."`, even though the Knowledge Graph for this document visibly
contained a `Germany` node.

### Bug I (partially fixed) — PII masking runs before entity extraction, so a masked person was never a graph node at all

Ingestion's critical path masks PII (`pii_vault` stage) *before* chunking and indexing; graph
extraction (`build_graph_for_document`, `app/graphrag/service.py`) runs afterward, as
enrichment, over those already-masked chunks. `extract_entities` (`app/graphrag/extractor.py`)
is spaCy NER, which has never seen the shape `<PERSON_6cc6eb>` before and tagged it as nothing —
confirmed directly: `extract_entities(...)` on the real sentence found `Germany` (GPE) but
nothing for the masked approver. `build_graph_for_document` requires *both* a triple's subject
and object to resolve to an entity its own NER pass found in that chunk, and explicitly drops
the triple otherwise (`"Couldn't link the triple's subject/object back to an entity ... dropped
rather than guessed at"` — a deliberate precision-over-recall choice, not an oversight). Since
the masked approver was never an entity, *no relationship involving them could ever become a
graph edge* — not just for this question, but for any relationship in any document where PII
masking replaced one side of it. **Fix**: `extract_entities` now also matches the PII token's
own format (`<ENTITY_TYPE_6hexchars>`, same shape `app/privacy/tokenizer.py` produces) and adds
each match as an entity labeled by its type (`PERSON`, `EMAIL_ADDRESS`, etc.) — recovering it as
a real, lookup-able graph node without the real value ever entering extraction, matching, or
storage. Confirmed live: the same document now has a `<PERSON_6cc6eb>` `PERSON` node alongside
`Germany`.

**This did not fully fix the symptom.** With the node now present, `graph` mode for the same
question still returns 0 evidence, because of a second, independent problem one layer deeper:
`extract_triples_llm`'s relation extraction is itself an LLM call, and — reproduced live,
deterministic at `temperature=0.0`, identical across 3 runs — it paraphrases rather than quoting
the NER surface forms: it extracts `'Head of Global Compliance' -- 'approval' --> 'is required'`
(the *role*, not the `<PERSON_6cc6eb>` token actually in the text) and `'Contractors' -- 'who
are' --> 'based in Germany'` (the object is `"based in Germany"`, not the bare entity text
`"Germany"` the GPE node is keyed on). `build_graph_for_document`'s subject/object matching is
exact-normalized-string-only, so neither triple links to either node, and no edge forms, even
though both nodes now exist. Fixing this properly means either fuzzy/substring matching between
a triple's subject or object and known entity mentions (the same kind of leniency
`resolve_entities` already applies when deduplicating NER mentions — see
`app/graphrag/resolver.py`), or reworking `_TRIPLE_PROMPT` to require the triple's subject/object
to be copied verbatim from a provided entity list rather than freely paraphrased. Either is a
real design change to a different function than the one just fixed, not a quick follow-on, so
it's tracked as a separate, not-yet-attempted next step rather than rushed here.

**Verified**: `backend/tests/test_graphrag_extractor.py`
(`test_extract_entities_recognizes_a_masked_pii_token`) and
`backend/tests/test_graphrag_service.py`
(`test_build_graph_creates_a_node_for_a_masked_pii_token`) cover the entity-recognition fix that
*is* complete. `graph` mode remains unreliable for questions whose answer involves a masked
person until the triple-linking gap above is addressed — `agentic` and `hybrid` modes are
unaffected (they don't use the knowledge graph as their primary retrieval path for a direct
question like this one; `agentic` only consults it as one of several tools).

## Infrastructure: a native macOS Metal/GPU crash under heavy concurrent model inference

**Symptom.** `ingestion.spec.ts`'s two "reaches ready within 60s" tests both failed —
`getByText('ready', { exact: true })` never appeared — right after a backend log line:

```
-[AGXG17GFamilyCommandBuffer tryCoalescingPreviousComputeCommandEncoderWithConfig:nextEncoderClass:]:1094:
failed assertion `A command encoder is already encoding to this command buffer'
.../multiprocessing/resource_tracker.py:254: UserWarning: resource_tracker: There appear to be
1 leaked semaphore objects to clean up at shutdown
```

This is Apple's Metal framework asserting on a native command-buffer usage violation inside
whichever ML library (torch/sentence-transformers, used by the embedder/reranker/PII detector)
was running GPU inference at the time — not Python, not application code, and not something a
`try`/`except` in this codebase can catch or recover from. Observed for the third time this
project (the first two weren't yet written up); each time it's followed heavy, repeated
concurrent model usage within one long-lived backend process — exactly this session's own
pattern of dozens of manual test uploads/chats plus a Playwright run in the same window.

**Confirmed infrastructure, not a code regression**: a plain `curl` upload/poll of the identical
file against the same running process completed in ~5s immediately beforehand; after a clean
`pkill -9` + restart (no code change), the exact same 5 ingestion tests that had just hung for
60s each passed in 26.4s total. The crash appears to leave whatever model call was in flight
(or a shared lazy-loaded model object) in a stuck state for the rest of that process's life,
rather than erroring cleanly — so one bad native assertion silently turns into "ready never
appears" much later, for unrelated requests, with nothing in the Python-level logs pointing
back to it unless the full log is actually read.

**Mitigation, not a fix**: there's no code-level recovery from a native Metal assertion inside a
third-party library's compiled GPU kernel. When ingestion or chat inexplicably hangs/times out
with the backend otherwise reporting healthy, grep its log for `AGXG17` / `MTLCommandBuffer` /
`failed assertion` / `leaked semaphore` before assuming an application bug — if present, restart
the backend (`pkill -9 -f "uvicorn app.main:app"`, verify `pgrep` is empty, start fresh) and
re-run, per the same pattern already used for the zombie-process incident above. Not re-triaged
as a flaky test to "just re-run": the test itself is correct and passes reliably once the
process is healthy.

**Escalation — confirmed reliably reproducible, not an occasional fluke.** Running the entire
e2e suite in one invocation (`npx playwright test tests/e2e/`, all three spec files together)
crashed the backend process outright (not just one stuck request) twice in a row, from a
genuinely fresh restart each time, with two slightly different assertion sites in the same
Metal command-buffer code (`setCurrentCommandEncoder:` once, `tryCoalescingPrevious...` another
time) — both followed by the same `leaked semaphore` warning and the process exiting. Each time,
the log showed multiple uploads' embedding batches starting within the same second, overlapping
with an earlier upload's still-running background enrichment (graph extraction's own LLM/
embedding calls, per `app/ingestion/service.py`'s deliberate "critical path first, enrichment
after" design) — i.e. this is this backend's *own internal* asyncio concurrency across
simultaneously in-flight requests and background tasks, not Playwright's (`fullyParallel: false`
already serializes the test runner itself to one at a time). Isolated runs of each spec file
individually, or any two together right after a fresh restart, passed cleanly every time this
session — it's specifically the combination of "fresh document count go up fast" and "earlier
documents' background enrichment hasn't finished yet" that reproduces it. A real fix would mean
serializing all GPU-bound model calls (embedder/reranker/PII detector/graph extraction) behind
one lock so at most one touches Metal at a time — a genuine architectural change, not attempted
here.

This matters more than a workaround note: `tests/e2e/README.md`'s own documented instructions
say to run `npx playwright test` with no file filter — exactly the invocation that reproducibly
crashes the backend. There's also no `make` target that runs this suite at all right now
(`frontend-test` is `npm run test --if-present`, and no `test` script exists in
`package.json`, so `make test` silently no-ops on the frontend side) — so there's no CI
reference to fall back on for "how this is supposed to be run safely" either. Until the
underlying concurrency issue has a real fix, run spec files separately
(`npx playwright test tests/e2e/<file>.spec.ts`) and restart the backend between heavy batches,
and treat updating the README's instructions and wiring up a real frontend test target as
follow-ups in their own right, not assumed to already be handled elsewhere.

**Fourth occurrence**, verifying the Workspace scroll fix below: a long single `npx playwright
test` invocation covering `workspace-scroll.spec.ts` plus the three pre-existing spec files (15+
real ingestions back to back) crashed the backend again — but this time while parsing an
unrelated document in `ingestion.spec.ts`, i.e. nowhere near the scroll fix's own code paths,
and `chat.spec.ts`'s unanswerable-question test separately showed the local LLM's own answer-
phrasing non-determinism (a correct-but-differently-worded abstain, not the hardcoded `/don't
have enough/i` regex) on the first retry after the crash-triggered restart — a second, unrelated
pre-existing flake, not a regression either. Restarting both the backend and Ollama (the crash
appears to able to leave Ollama's own GPU-backed inference degraded too, not just the Python
process that triggered it — a 30s `litellm.Timeout` on every call until Ollama itself was
restarted) and re-running each spec file separately confirmed everything green. Logged here
rather than re-litigated: this is the same infrastructure issue above, not evidence against the
scroll fix, and running large multi-spec e2e batches on this machine should still be expected to
need a mid-run restart.

## Incident: two-finger trackpad scroll was dead in Workspace's chat and dashboard panes

**Symptom.** Neither the chat message list nor the document-intelligence (dashboard) panel in
Workspace responded to a two-finger trackpad scroll, mouse wheel, or touch drag. Keyboard scroll
(arrows/PageUp/PageDown) didn't work either. The composer and the rest of the page were fine —
scrolling just did nothing inside either pane.

### Root cause

`src/lib/smooth-scroll.tsx` wraps the entire app in `<ReactLenis root>` (a virtual smooth-scroll
library) with no exclusions anywhere. Lenis's own wheel/touch handler walks the composed event
path and only lets the browser's native scroll run on an element if it (or an ancestor) carries
`data-lenis-prevent` (`node.hasAttribute('data-lenis-prevent')`,
`node_modules/lenis/dist/lenis.mjs:609`) — confirmed by grepping the whole `src/` tree for that
attribute: zero hits. So every wheel/touch event over either pane was captured by Lenis first,
which tried to smooth-scroll the page root — which had nothing left to scroll inside the
`h-screen` layout, since the two panes (not the page) are where the actual overflow lives. The
panes' own `overflow-y: auto` never got a chance to act on the event at all.

Confirmed directly, not just by code reading: running `page.mouse.wheel` (small, trackpad-sized
deltas) over the pre-fix chat pane in a real browser left its `scrollTop` at `0`.

A second, independent issue surfaced only once seeding real overflow at narrow viewport widths
(1024×600): the ingestion Stepper's 10 non-shrinking step circles have an unavoidable
min-content width (~556px) that, stacked against the fixed 240px nav rail and the dashboard
panel's fixed 400px width, didn't fit — pushing the dashboard panel off the right edge of the
viewport entirely (confirmed via each element's real `getBoundingClientRect()`). Pre-existing,
unrelated to Lenis, just never exercised at exactly that width before.

### The fix

**1.** `data-lenis-prevent` + `tabIndex={0}` (native keyboard scrollability) on both panes'
actual scroll containers: the chat pane (`workspace-page.tsx`, now `data-testid="chat-scroll-
pane"`) and `document-intelligence-panel.tsx`'s root. **2.** The page's outer `h-screen` →
`h-dvh` (correctness on mobile viewports with a dynamic browser toolbar). **3.** `min-w-0` on
the chat column plus `overflow-x-auto` scoped to just the Stepper's row, so a width floor that
can't shrink any further scrolls inside its own card instead of forcing the whole page wider.
**4.** Chat auto-follow (`scrollRef`'s effect) now only runs while the user is already within
48px of the bottom (tracked via a scroll-position ref, since the effect itself can't read live
scroll state); otherwise a "Jump to latest" chip appears over the pane.

**Verified**: `frontend/tests/e2e/workspace-scroll.spec.ts` (chromium + webkit, SC-6) — wheel
(fractional, trackpad-style) and keyboard scroll on both panes, independence between the two,
composer staying pinned, the Jump-to-latest chip, and three additional viewport sizes (1280×720,
1024×600, 390×844 mobile, where the dashboard panel's existing `lg:` breakpoint intentionally
hides it). Confirmed failing against the pre-fix commit (wheel left `scrollTop` at `0`) and
passing after.
