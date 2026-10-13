# Evaluation

How Veritas measures itself — every number described here comes from a real computation
against a real document, never a lookup table. See [docs/BENCHMARKS.md](BENCHMARKS.md) for the
most recent actual run's numbers and [docs/DECISIONS.md](DECISIONS.md) for the reasoning
behind specific thresholds/weights.

## Estimated vs. Verified

The one labeling rule that applies everywhere a quality score is shown:

- **Estimated** — reference-free. The LLM judge scores an answer against its own retrieved
  context, with no ground-truth answer to check against. This is what every live chat turn
  gets (`ChatReport.quality`, `app/evaluation/judge.py`) — there's no ground truth available
  at chat time, so "Verified" never applies there by construction.
- **Verified** — scored against a real ground-truth answer from the synthetic eval set
  (`correctness`, in the benchmark runner). Only exists where a dataset with known answers
  does.

Both use the *same* scoring functions (`score_faithfulness`, `score_relevancy`,
`score_correctness` in `app/evaluation/judge.py`) — the caller decides the label based on
whether ground truth was available, not the scoring function itself.

## Synthetic dataset generation

`app/evaluation/datasets.py::generate_dataset(document_id, target_size)` builds eval items
from a document's own real persisted chunks and real graph edges — never hand-written
fixtures pretending to be generated:

| Category | Source |
|---|---|
| `factoid` | One real chunk, one LLM-generated question+answer about it |
| `multi_hop` | Two chunks linked by a real graph edge |
| `comparison` | Two chunks, asked to compare/contrast |
| `unanswerable` | A real chunk, deliberately asked about something it doesn't contain |
| `pii` | A chunk the pipeline already flagged as containing a masked PII token |

A final embedding-similarity pass drops near-duplicate questions, so `item_count` is usually
below `target_size` — that's real filtering, not padding back up to the requested count.
Persisted as versioned JSONL under `data_dir/eval_datasets/{document_id}/v{N}.jsonl`.

## Metrics

- **Retrieval** (`app/evaluation/metrics/retrieval.py`): precision@k, recall@k, hit@k, MRR,
  nDCG@k — textbook formulas, computed from real retrieved-vs-relevant chunk ID sets.
- **Generation** (`app/evaluation/judge.py`): faithfulness, relevancy, correctness (0-10 LLM
  scoring, normalized to 0-1), plus a deterministic `citation_validity` check (do `[n]` markers
  in the answer actually reference a real context item).
- **Safety**: the real red-team suite's block rate, and `_measure_pii_leak_count` — a real
  Presidio scan over every indexed chunk's text, which should always be zero (masking happens
  before indexing) and is verified empirically rather than assumed.
- **System**: p50/p95 latency per config, measured with `time.perf_counter()` around the real
  call.

## Profiler + Advisor (the chunking tournament)

`app/profiler/features.py::profile_document` computes real document features (heading/table/
list/code density, entity density, graph relation density, an LLM-guessed document type).
`app/profiler/tournament.py::run_tournament` then runs 5 real candidate configurations
(different chunking strategies/sizes, reranker on/off, an alternate LLM) against the generated
eval set, scoring each with the real retrieval metrics + judge. `app/profiler/advisor.py`
turns the winner into a Baseline-vs-Suggested recommendation with a rationale tied to the
actual measured numbers.

This runs automatically during ingestion once a document has enough chunks to make the
comparison meaningful (`MIN_CHUNKS_FOR_TOURNAMENT`), and on demand via `POST
/documents/{id}/advisor/run`. **Accept** (`POST .../advisor/decision {"decision": "accept"}`)
is a real re-chunk/re-embed/re-index with the suggested config — not a config flag flip; see
docs/DECISIONS.md for exactly what it deletes and rebuilds.

## Benchmark runner

`app/evaluation/benchmark.py::run_benchmark` scores real configs
(`bm25`, `dense`, `hybrid`, `hybrid_rerank_hyde`, `graph`, `agentic`, and `agentic_council` when
explicitly requested) against a fresh synthetic dataset, plus the real red-team suite for the
safety signal. Hard production gates: faithfulness >= 0.85, injection block rate >= 95%, zero
PII leaks, p95 latency <= 15s. `recommended_config()` picks the highest production score among
configs that pass every gate, or — honestly, when none do — the highest score overall, so
there's always an answer to "what would ship today" without claiming it's actually ready.

Run it: `make eval` (ingests the bundled demo document and runs the full suite, writing
`docs/BENCHMARKS.md`), or `POST /eval/benchmarks/run` for a specific document via the API/UI.


## How the Evaluation tab reads these numbers

- **Verified vs Estimated.** Retrieval metrics (precision, recall, nDCG, MRR @5) and
  correctness are *Verified*: computed against the eval set's labelled chunks and reference
  answers. Faithfulness and answer relevance are *Estimated*: a judge model's opinion with no
  reference. Scores on live Workspace answers are always Estimated.
- **Not measured is not zero.** A judge call that fails or times out yields `null`, shown as
  "Not measured", and is excluded from averages; `n_judged` says how many questions each
  number rests on.
- **Deltas** compare a run only with the previous run on the same eval set.
- **Provenance** is stored per run (`run_config`): judge, generator, embedding and reranker
  models, chunking, eval-set version, question count, duration. Runs from the first harness
  (`harness_version` null) were scored differently and are hidden from the trend.
- **Strategy comparison** (`POST /rag/compare`) runs each strategy on identical questions and
  reports per-metric differences against a baseline. Under 10 questions it is labelled a
  small sample; differences inside 0.02 are a tie.
- **Agentic and council strategies** generate answers for at most five questions per run to
  keep a local run to minutes; their retrieval metrics cover the whole set.
