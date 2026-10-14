# Using Veritas

Three tabs: **Workspace**, **Architecture**, **Evaluation**. Everything shown is read from
the running backend; a value that has not been measured says "Not measured".

Start it with `make dev` (backend on :8000, frontend on :5173) and open
<http://localhost:5173/app>. Ollama must be running (`ollama serve`).

## 1. Workspace — upload and ask

1. Drop a file on the upload area, or click **Or try the bundled sample**. The stepper shows
   each ingestion stage as it really happens; chat unlocks at "ready". Graph extraction and
   profiling continue in the background and never block chat.
2. Type a question. Every question gets a **quick answer of 3–4 lines**.
3. Turn on **Deep reasoning** (the button above the question box) for a **7–8 line** answer.
   It stays on until you turn it off.
4. The answer streams in as the model writes it. Under it you see which strategy and model
   answered, the measured time, and — once scoring finishes — how many sentences are supported
   by the retrieved text. Click a citation chip to see its source.

**Switch the retrieval strategy** with the first button in the header (for example
"Hybrid + Rerank"). Each option says what it is best for and its latency: "measured" when
this machine has run it, "typical" otherwise. A strategy that needs an index or a graph the
document does not have offers to build it.

**Switch the answer model** with the second button. Only models installed in your Ollama are
listed, with size and whether one is loaded. A warning appears if the selection would not fit
the machine's memory tier. "More model settings" opens judge, council, embedding and reranker
choices; changing the embedding model marks the index stale and offers a re-index.

**Best strategy, picked automatically.** After an upload, once the graph has been read, the
app writes five questions with known answers from the document and runs Hybrid, Hybrid +
Rerank and GraphRAG (where available) on them — usually one to two minutes, in the
background, always after your own questions. The highest combined quality score (0–1:
faithfulness, relevance, correctness and ranking) becomes the strategy that answers this
document. The card on the right shows the winner with its score and every measured
strategy's score; until the measurement finishes it shows a prediction from the document's
shape, marked "not measured yet". **Compare for details** runs the same question set again
with the document's strategy as the baseline; tick any other strategy (Agentic included) to
put it next to the recommended one, or switch to "One question" to try your own. It shows the
answers side by side question by question; **Re-measure** runs it again. Picking a strategy for the document
yourself (the card, the strategy picker, or "Adopt" in a comparison) sticks: automatic
measurement never overrides your choice. Five questions is a small sample and the card says
so.

**History.** Conversations are kept per document in the browser, so a reload or coming back
to an earlier document (document switcher, top right, which lists every ingested file) shows
the same chat. "Clear chat"
removes it.

## 2. Architecture — how it works, live

- **Overview / Detailed / Live Trace** switch the level of detail. The diagram is built from
  the code: packages are discovered, the agent's nodes come from the compiled LangGraph.
- The strip of pills is a live health probe per subsystem. **Run self-check** exercises the
  real pipeline end to end and reports each step.
- Ask a question in Workspace with this tab open on **Live Trace**: bright packets travel the
  edges and nodes ripple as each real stage runs. Close the socket and they stop.
- **Play request path** walks the declared route of a question through the system. It is
  labelled as an illustration and is never mixed with live traffic.
- Faint drifting dashes only show which way an edge flows. Click any node for its purpose,
  configuration, recent events and source file. **Export** saves PNG, SVG or the JSON.

## 3. Evaluation — one dashboard, three views

| View | What it answers |
| --- | --- |
| **Usage** | What did real questions look like? Volume and quality by day, strategy mix, time per pipeline stage, reliability. Below that, **Measured quality**: run an evaluation and read faithfulness, relevance, precision/recall@5, the trend across runs, the per-strategy table and radar, speed, release gates and the chunking advisor. |
| **Knowledge graph** | The entities, concepts and relations read from the document. **Ask the graph** a question: the traversal lights up and a real answer is written through the graph strategy. **Rebuild graph** reads it again (about a minute). |
| **Safety** | Guardrail decisions on real questions, trips by rule, the audit log, and a red-team suite you can run. |

An evaluation or comparison uses **at most five questions** (three for the agent strategies),
picked across question types, so two or three strategies finish in one to two minutes. Every
result shows the number of questions it rests on, and anything under ten is labelled a small
sample.

Numbers are labelled **Verified** (checked against ground truth from the question set) or
**Estimated** (a judge model's opinion, no reference answer). A change is only shown against
the previous run on the same questions.

## Keyboard

`⌘K` / `Ctrl K` opens the command palette (go to a tab or Evaluation view, switch strategy,
toggle Deep reasoning, run an evaluation, switch document). `Enter` sends, `Shift Enter` adds
a line. Every control is reachable with Tab; reduced-motion preferences are respected.

## Memory and speed on a 16 GB laptop

Only two models stay in memory: the answer model `llama3.2:3b` (about 2.3 GB) and the small
safety model (about 1.7 GB). Any other model (a council member, a separately chosen judge) is
unloaded as soon as it has replied, and idle models are unloaded after five minutes
(`OLLAMA_KEEP_ALIVE`). `gemma3:4b` was removed because it alone held 3.8 GB; larger models are
only loaded if you install and pick them. See `docs/TROUBLESHOOTING.md` if answers are slow.
