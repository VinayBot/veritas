# Demo data

- `hr_handbook.md` — a real, substantial HR policy document (14 sections, one real-shaped
  PII pair: a name and an email) used by `make eval` (`backend/scripts/run_eval.py`) to ingest
  and benchmark against when no document is specified. Long enough to clear
  `MIN_CHUNKS_FOR_TOURNAMENT` so the profiler/advisor tournament and GraphRAG extraction both
  run for real against it, not just the retrieval configs.

Not yet populated, per the original build brief: a messy/OCR'd PDF containing PII (to exercise
the refiner's quality-repair path and the PII vault's non-plain-text extraction together), and
a curated list of demo URLs for the scraper. Left as an honest gap rather than fabricated —
see docs/VALIDATION_REPORT.md.
