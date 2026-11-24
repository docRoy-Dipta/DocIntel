# Project requirements

Source: the master project prompt, analysed in Phase 0. Status values: **Done** = implemented and covered by automated tests;
**Done (untested live)** = implemented, but a part that depends on an external service/tool could not be run in development;
**Partial** / **Not done** = see the note.

## Functional requirements

### Module A — Document processing
| Requirement | Status | Notes |
|---|---|---|
| Multi-file upload | Done | up to `MAX_FILES_PER_REQUEST` (20) files per request, per-file results |
| File type and size validation | Done | content-based (magic bytes), extension must match; `MAX_UPLOAD_MB` (200), enforced while streaming |
| Digital PDF text extraction | Done | PyMuPDF, page by page, with word boxes |
| OCR for scanned PDFs and images | Done | Tesseract 5, English; engine is behind an interface |
| Multi-page processing | Done | one job per page; TIFF frames, PDF pages |
| Excel with multiple sheets | Done | XLSX + XLS; one page per sheet |
| CSV | Done | encoding (UTF-8/BOM/UTF-16 with BOM/cp1252) and delimiter detection |
| Image preprocessing | Done | autocontrast, deskew (measured benefit in EVALUATION_REPORT), optional denoise/binarize |
| Corrupted-file detection | Done | opened with the real parser; truncated PDFs are repaired but forced to review; encrypted rejected |
| Duplicate file detection | Done | SHA-256; the existing document is returned |
| Processing logs and error handling | Done | `processing_events` per document, structured JSON logs, request ids |

### Module B — AI information extraction
| Requirement | Status | Notes |
|---|---|---|
| Fields: number, date, supplier, customer, subtotal, tax, total, currency, line items | Done | plus `tax_rate` when the document states one |
| Structured JSON; `null` for missing; never invent | Done | grounding check drops values not found in the source |
| Preserve original text; confidence; page and location | Done | `raw_text`, `confidence`, `page`, `bbox` ([x0,y0,x1,y1] or sheet+cell) |
| Extracted vs inferred | Done | `source` field; inferred values are capped at 0.6 confidence and always reviewed |
| Manual review for uncertain results | Done | review queue, corrections, approval |
| LLM extraction with structured output | Done (untested live) | Gemini extractor with JSON schema, tested only against a mocked HTTP transport |
| Rule-based extractor | Done | `heuristic` — free, offline baseline (this is what was evaluated) |

### Module C — Financial validation (all deterministic, `Decimal`)
Required fields, missing information, numeric sanity, line math, subtotal, tax (incl. stated rate), total, currency consistency/validity,
date plausibility/ambiguity, duplicate invoices, discrepancy flags and manual-review flags: **Done** (each rule has a unit test).

### Module D — Cross-document verification
PDF↔PDF, PDF↔Excel, invoice↔receipt; matching by invoice number then supplier+total; supplier/customer, amount, currency, date comparison;
evidence (file, page, bbox, sheet+cell) and rule for each verdict: **Done**.

### Module E — Backend API
Uploads, status, results, details, search, corrections, failed-job reprocessing, history, cross-document verification: **Done**
(see [API_DOCUMENTATION](API_DOCUMENTATION.md)). Heavy work runs in the background.

### Module F — Database and search
All listed data stored (see [DATABASE_SCHEMA](DATABASE_SCHEMA.md)). Keyword (PostgreSQL FTS), filters, semantic (pgvector): **Done**.
*Semantic search uses a dependency-free hashing embedder by default (lexical overlap, not deep meaning); `sentence-transformers` is supported but was not run.*

### Module G — Frontend (Next.js + TypeScript + Tailwind)
Dashboard, multi-upload with progress, document list, preview (with highlighted evidence), extracted data, validation results,
manual correction, comparison, search, processing history: **Done** (builds, type-checks strictly, and matches the API contract; **not exercised in a real browser**).

### Module H — Testing and evaluation
All test types implemented; measured accuracy, P/R/F1, timings, success/failure rates, validation and cross-document metrics:
**Done on a synthetic labeled dataset** — see [EVALUATION_REPORT](EVALUATION_REPORT.md) for what that does and does not prove.

## Non-functional requirements

| Requirement | Status | Evidence |
|---|---|---|
| Thousands of documents; ~1,000-page PDFs | Done | page-level jobs; measured 1,000-page run in TESTING_REPORT |
| No whole-document memory loads; never send 1,000 pages to an LLM | Done | streaming reads; extraction per logical document, chunked by `LLM_PAGES_PER_CALL` |
| Retries, idempotent jobs, recovery | Done | autoretry with backoff; atomic stage claims; stalled-document reaper; real SIGKILL test |
| Indexing, API latency | Done | indexes in the schema; latencies in TESTING_REPORT |
| Security | Done (see [SECURITY](SECURITY.md)) | authn/authz, rate limits, upload hardening, audit log |
| Docker / Compose / Git / CI | Written; Compose **untested** | `docker-compose.yml`, Dockerfiles, GitHub Actions workflow |

## Deliberate differences from the original stack

| Spec | What was done | Why |
|---|---|---|
| pandas | Not used | `openpyxl`, `xlrd` and `csv` are enough and lighter (streaming, no dtype surprises). |
| Tesseract **or** PaddleOCR | Tesseract only | Simplest to install in Docker; PaddleOCR can be added behind the same `OCREngine` interface and compared on the evaluation set. |
| Embeddings (any) | Hashing embedder by default; optional sentence-transformers | Free, offline and deterministic; real semantic quality needs the optional package. |
| Celery `verify` queue | Not created | Comparisons are cheap and run inside the request. Queues: `parse`, `ocr`, `llm`. |
