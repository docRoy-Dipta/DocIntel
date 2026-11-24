# Testing report

*Generated 2026-11-23 10:44 UTC by `scripts/gen_reports.py` from the files in `docs/`. Everything below was measured by running the commands shown; nothing is estimated.*

## How to reproduce

```bash
cd backend && pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy        # static checks
pytest -q --cov=app                                  # test-suite (real PostgreSQL + pgvector, Celery in eager mode)
python scripts/e2e_real_stack.py                     # real Redis + separate worker process + SIGKILL crash test
python scripts/perf_test.py 1000                     # ~1,000-page PDF + API latency
python scripts/evaluate.py                           # labeled-dataset evaluation -> EVALUATION_REPORT.md
python scripts/ui_contract_check.py                  # frontend/backend contract check (needs `npm run build`)
```

## Test environment

Python 3.12.3, 1 CPU, Linux-6.18.44-fc-v726-x86_64-with-glibc2.39. PostgreSQL 16 + pgvector 0.6 (via `pgserver`), Tesseract 5.3, Redis 7.0 (e2e only).

## Test-suite result

**181 passed, 0 failed, 0 skipped** in 42 s (total statement coverage of `app/`: **92.7%**).

| Test module | Passed | Failed | Skipped | What it covers |
|---|---:|---:|---:|---|
| `tests/test_ai_and_processors.py` | 37 | 0 | 0 | Unit/AI/OCR/spreadsheet: classification, grounding, scoring, Gemini client (mocked HTTP), file safety, spreadsheet mapping, OCR, embeddings, rate limiting |
| `tests/test_domain.py` | 76 | 0 | 0 | Unit: money & date parsing, every financial-validation rule, record matching |
| `tests/test_migrations.py` | 2 | 0 | 0 | Database: migrations apply, roll back, and match the models |
| `tests/test_pipeline_api.py` | 19 | 0 | 0 | Integration + API: whole pipeline for every input type (digital/scanned PDF, PNG/JPEG, TIFF, XLSX, XLS, CSV) |
| `tests/test_recovery.py` | 3 | 0 | 0 | Failure scenarios: lost queue messages / stalled documents |
| `tests/test_review_and_failures.py` | 13 | 0 | 0 | API + failure scenarios + AI safety: corrections, approvals, reprocessing, transient/permanent failures, hallucination & prompt injection |
| `tests/test_search_and_compare.py` | 7 | 0 | 0 | API: keyword/semantic/hybrid search, filters, cross-document verification |
| `tests/test_security_api.py` | 14 | 0 | 0 | Security: authn/authz, forged tokens, upload hardening, zip/decompression bombs, rate limits, injection |
| `tests/test_smoke.py` | 10 | 0 | 0 | Smoke: package layout |

### Coverage by package

| Package | Statements | Covered | % |
|---|---:|---:|---:|
| `app/ai` | 488 | 462 | 95% |
| `app/api` | 431 | 394 | 91% |
| `app/app (root)` | 62 | 58 | 94% |
| `app/core` | 181 | 162 | 90% |
| `app/db` | 232 | 232 | 100% |
| `app/devtools` | 210 | 199 | 95% |
| `app/domain` | 393 | 382 | 97% |
| `app/processors` | 721 | 647 | 90% |
| `app/repositories` | 0 | 0 | — |
| `app/schemas` | 181 | 181 | 100% |
| `app/services` | 1089 | 995 | 91% |
| `app/tasks` | 168 | 142 | 85% |

Lines not covered are mostly: the real Gemini network path beyond the mocked transport, the optional sentence-transformers embedder, Redis-specific code paths exercised only by `e2e_real_stack.py`, and defensive error branches.

## Requirement → test mapping (Module H)

| Required test type | Where |
|---|---|
| Unit | `test_domain.py`, `test_ai_and_processors.py` |
| Integration | `test_pipeline_api.py` (API + PostgreSQL + pipeline), `test_migrations.py` |
| API | `test_pipeline_api.py`, `test_review_and_failures.py`, `test_search_and_compare.py`, `test_security_api.py` |
| OCR | `test_ai_and_processors.py::test_ocr_*` (clean, rotated, noisy, JPEG-compressed scans), `test_pipeline_api.py` (scanned PDF, PNG, JPEG, multi-page TIFF) |
| Spreadsheet parsing | `test_ai_and_processors.py` (header offsets, decorated headers, CSV encodings/delimiters, formulas without cached values, row limit), `test_pipeline_api.py` (XLSX summary & line layouts, multi-sheet, XLS, CSV) |
| AI extraction | `test_ai_and_processors.py` (grounding, scoring, Gemini request/response/errors/rate limit with mocked HTTP), `test_review_and_failures.py` (hallucination rejected, prompt injection) |
| Validation | `test_domain.py` (every rule has a positive test; tolerance edge cases) |
| Failure scenarios | `test_review_and_failures.py` (page failure → retry, LLM timeout → retry → recover, idempotency/claims), `test_recovery.py` (lost messages), `test_pipeline_api.py` (corrupt, truncated, encrypted, duplicate), `e2e_real_stack.py` (worker SIGKILL) |
| Performance | `scripts/perf_test.py` (below) |
| Security | `test_security_api.py` |

## Real-stack end-to-end run (`scripts/e2e_real_stack.py`)

Real Redis broker, real PostgreSQL, a **separate Celery worker process**, the API server over HTTP, and a `SIGKILL` of the worker in the middle of OCR.

```text
PASS  all four documents finished: {'bundle': 'completed', 'scan': 'completed', 'xlsx': 'needs_review', 'csv': 'completed'}
PASS  bundle PDF was split into 8 invoices by separate worker processes
PASS  every invoice number extracted correctly, in order
PASS  spreadsheet and CSV records extracted
PASS  scanned PDF went through the OCR queue
PASS  document is mid-flight when the worker is killed (2/6 pages done)
      worker killed with SIGKILL; starting a replacement worker
PASS  document recovered after the crash -> completed
PASS  all 6 invoices were recovered after the worker crash
      recovery events: ["Stalled in 'processing'; re-queued (pages)"]
      dashboard: {'documents_total': 5, 'by_status': {'uploaded': 0, 'queued': 0, 'validating': 0, 'processing': 0, 'analyzing': 0, 'completed': 4, 'needs_review': 1, 'failed': 0, 'rejected': 0}, 'pages_processed': 21, 'pages_ocr': 8}
ALL CHECKS PASSED
```

## Performance (`scripts/perf_test.py`)

Document: **1002 pages**, 334 invoices, 3.36 MB (digital PDF). Mode: single process, eager Celery (no broker), PostgreSQL 16 on the same machine.

| Measurement | Result |
|---|---|
| Final status | completed |
| Total pipeline time | 22.7 s (44.2 pages/s) |
| Invoices found | 334 of 334 |
| Process memory before / after / peak | 186 MB / 214 MB / 219 MB |

Memory stays flat because each page is read, stored and released on its own (the PDF is never loaded as a whole).

API latency while the database holds those pages (in-process client, so network time is excluded):

| Endpoint | n | p50 | p95 | max |
|---|---:|---:|---:|---:|
| `GET /documents` | 200 | 4.7 ms | 6.3 ms | 10.1 ms |
| `GET /documents/{id}/status` | 200 | 4.9 ms | 6.4 ms | 7.8 ms |
| `GET /invoices (filtered)` | 200 | 6.2 ms | 9.3 ms | 86.4 ms |
| `GET /search keyword` | 100 | 19.2 ms | 22.3 ms | 31.0 ms |
| `GET /search semantic` | 100 | 8.7 ms | 10.6 ms | 90.5 ms |
| `GET /search hybrid` | 100 | 21.5 ms | 30.9 ms | 107.2 ms |
| `GET /stats/dashboard` | 50 | 8.8 ms | 11.7 ms | 14.8 ms |

Not measured: throughput with several parallel workers on a multi-core machine, OCR throughput on a 1,000-page *scanned* PDF (OCR cost measured per page in the evaluation instead), and behaviour with a real (non-mocked) LLM.

## Frontend ↔ backend contract (`scripts/ui_contract_check.py`)

37 checks passed, 0 failed: all page routes are served by the built Next.js app, CORS allows the frontend origin and refuses a foreign one, and every TypeScript interface in `frontend/lib/api.ts` was compared with a real API response.

**Not tested:** user interactions in a real browser (clicking, drag-and-drop, the bounding-box overlay). The sandbox used for development could not download a browser. Static checks that were run: TypeScript strict mode and `next build`.

## Known gaps

- `docker compose` (Dockerfiles, compose file) could not be executed in the development sandbox: they are untested until first run on a machine with Docker.
- The Gemini extractor was tested only against a mocked HTTP transport (request shape, parsing, error handling, rate limiting). It has never talked to the real API.
- Load testing with many concurrent users was not done.
