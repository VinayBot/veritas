# Test fixtures

Shared across backend pytest, frontend Playwright, and the quality/eval runner — one set of
real files instead of three divergent copies.

| File | Purpose | Real content? |
|---|---|---|
| `small_two_page.pdf` | 2-page text PDF, happy path | Yes — IT equipment & device policy, 8 facts |
| `long_fifty_pages.pdf` | 61-page text PDF, long-document retrieval | Yes — 15-chapter employee handbook, facts spread through the whole document including the last chapter |
| `scanned_image_only.pdf` | PDF with zero extractable text (rendered-image page, no text layer) | Real text, but delivered as a raster image — exercises the no-OCR/unparseable-text path |
| `sample.docx` | DOCX format | Yes — expense reimbursement policy, 7 facts |
| `non_english.pdf` | Non-English (French) document | Yes — paid leave policy, 6 facts, questions in French |
| `empty.pdf` | 0-byte file | — (deliberately broken) |
| `corrupted.pdf` | Random bytes with a `.pdf` extension | — (deliberately broken) |
| `golden_qa.json` | 5-10 real question/expected-answer pairs per good document above | — |

**`oversized.pdf` is generated on demand, not committed** — see `make_oversized.py`. A 25MB+
blob of random bytes has no stable content worth version-controlling; any such blob exercises
the same code path (`MAX_UPLOAD_BYTES` in `backend/app/api/routes/documents.py`, currently
25MB). Run `python tests/fixtures/make_oversized.py` to create it locally; it's gitignored.

All source HTML/generation scripts for the PDFs above are not checked in (one-off rendering via
Playwright's `page.pdf()` and Pillow's image-to-PDF — the same technique already used for
`data/demo/northwind_remote_work_travel_policy.pdf`); only the resulting fixture files are.
