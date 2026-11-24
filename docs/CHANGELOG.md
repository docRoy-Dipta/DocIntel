# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versions follow SemVer.

## [0.1.0] — unreleased (first complete build)

### Added
- Repository tooling: Ruff, mypy (strict), pytest, pre-commit, GitHub Actions workflow, EditorConfig, line-ending normalisation.
- **Backend** (FastAPI): auth (JWT, roles), documents, pages, history, extraction results, corrections, approval, reprocessing, search, invoice listing,
  comparisons, dashboard statistics, audit log, health checks; consistent error envelope; rate limiting; security headers.
- **Pipeline** (Celery + Redis): page-level jobs, OCR queue, atomic stage claims, retries with backoff, failure recording, stalled-document reaper (Celery beat).
- **Processing:** content-based file detection and integrity checks; PDF text layer; OCR with deskew; image/TIFF; XLSX/XLS/CSV with header detection and column mapping; page classification and bundle splitting.
- **AI:** rule-based extractor, Gemini extractor (JSON-schema output, rate limit, retries), grounding, computed confidence, chunking/merging, hashing and optional sentence-transformer embeddings.
- **Validation:** deterministic rules (required fields, line/subtotal/tax/total arithmetic, tax rate, currency, dates, duplicates).
- **Cross-document verification** with evidence; keyword/semantic/hybrid search with filters.
- **Database:** 14 tables, Alembic migration `0001`, FTS (GIN) and vector (HNSW) indexes.
- **Frontend** (Next.js 15, TypeScript, Tailwind): dashboard, upload with progress, document list, document detail with preview and highlighted evidence, correction, comparison, search, history.
- Docker Compose stack (db, redis, migrate, api, worker, beat, frontend), Dockerfiles.
- Synthetic invoice generator, evaluation, performance and real-stack end-to-end scripts; generated API/DB/test/evaluation documentation.

### Fixed during development (found by tests/measurement)
- Retry of a partially failed bundle could never recover the lost invoice (split is now reconciled on resume).
- CSV in legacy 8-bit encodings was mis-detected as UTF-16 (UTF-16 now requires a BOM).
- Line items were lost when OCR produced text rotated by deskew mapping (text is now rebuilt from straightened coordinates).
- Totals rows like "Tax (10%) $2.55" were mis-parsed as 102.55 by the grounding check.
- Summary-level spreadsheets no longer trigger "no line items" review noise; summary vs line-item comparisons report `not_comparable` instead of a discrepancy.
- Repaired (damaged) PDFs are always sent to review.
- Dashboard SQL join.
