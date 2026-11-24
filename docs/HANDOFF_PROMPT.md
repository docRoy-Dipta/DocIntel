# HANDOFF PROMPT — paste everything below into a new AI conversation

You are taking over an existing software project as a senior engineer and mentor. The owner (Roy, junior data analyst, learning while building) wants **clear, beginner-friendly explanations** with engineering quality, **exact file paths**, **complete working code**, and **no claims without verification**. You do not have access to the previous conversation. Everything you need is below and in the repository (`docs/`).

## 1. What the project does
An AI-powered **document intelligence system** for business/financial documents. Users upload invoices and receipts (PDF digital/scanned, PNG/JPEG/TIFF, XLSX/XLS, CSV). The system extracts structured data
(invoice number, date, supplier, customer, subtotal, tax, total, currency, line items) **with evidence** (raw text, page, bounding box, confidence, extracted-vs-inferred), validates the arithmetic **deterministically**, flags discrepancies for human review,
compares documents against each other (PDF↔PDF, PDF↔Excel, invoice↔receipt), and makes everything searchable (keyword + semantic + hybrid + filters) through a REST API and a Next.js web UI. A single PDF may contain ~1,000 pages = hundreds of invoices.

## 2. Architecture (modular monolith + workers)
Browser (Next.js) → FastAPI → PostgreSQL 16 + pgvector; FastAPI enqueues to Redis → Celery workers (queues `parse`, `ocr`, `llm`; Celery beat runs `requeue_stalled`).
Layers: `api/` (thin routes) → `services/` (pipeline stages, business ops) → `processors/` + `ai/` (readers, OCR, extractors) → `domain/` (PURE logic: money, dates, validation rules, matching) → `db/` (SQLAlchemy 2, sync) ; `tasks/` = thin Celery wrappers.
Pipeline: upload (stream+hash+magic-byte check+dedupe) → start (integrity check, page rows) → **one job per page** (text layer, or re-queued to `ocr`) → atomic claim `processing→analyzing` by the last page → analyze (classify pages, **split into logical documents**, embeddings) → one extract job per invoice (extractor → **grounding** → computed confidence → versioned extraction → validation) → atomic finalize `completed|needs_review`.
Key invariants: every stage is idempotent; hand-over uses `UPDATE ... WHERE status=X` claims; commit **before** enqueue; money is `Decimal`/`NUMERIC`; extractions are versioned and human corrections are separate rows layered on top; an LLM never decides pass/fail.

## 3. Tech stack
Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 (sync) + Alembic, psycopg 3, pgvector, Celery + Redis, PyMuPDF, Tesseract (pytesseract), Pillow/numpy, openpyxl/xlrd/csv, PyJWT, httpx. Optional: Gemini free-tier extractor, sentence-transformers embeddings.
Frontend: Next.js 15 (App Router), React 19, TypeScript (strict), Tailwind 3. Tooling: ruff, mypy --strict, pytest, pre-commit, Docker Compose, GitHub Actions.
Deviations from the original spec: no pandas (unneeded), Tesseract only (PaddleOCR not implemented), no separate `verify` queue.

## 4. Status
Implemented: **all spec modules A–H**. Verified: 181 tests (92.7% coverage), ruff/mypy clean, migrations, real Redis + separate worker + SIGKILL recovery, 1,000-page performance run, labeled synthetic evaluation, frontend type-check/build/route/CORS/contract checks.
**NOT verified**: Docker/Compose/CI (never run), the UI in a real browser, Gemini against the real API (only a mocked HTTP transport), real-world invoices (all accuracy numbers are on synthetic data and the rule-based extractor), sentence-transformers.
Not implemented: PaddleOCR, user-management UI/password reset, add/delete line items, carrying line-item corrections across re-extraction, non-English support, antivirus/sandboxing, httpOnly-cookie auth, S3 storage backend, LLM-assisted splitting/column mapping, licence choice (PyMuPDF is AGPL).

## 5. Known bugs / weaknesses
No known failing tests. Weaknesses: heuristic extractor assumes labelled English layouts; page splitting is rule-based; OCR errors in digits are caught only by arithmetic checks and low confidence; free-tier LLM rate limits; JWT in localStorage; see `docs/SECURITY.md` and the limitations table in `docs/CURRENT_PROJECT_STATE.md`.

## 6. Repository structure
```
.editorconfig
.env.example
.gitattributes
.github/
  workflows/
    ci.yml
.gitignore
.pre-commit-config.yaml
README.md
backend/
  .dockerignore
  Dockerfile
  alembic/
    env.py
    script.py.mako
    versions/
      0001_initial_schema.py
  alembic.ini
  app/
    __init__.py
    ai/
      __init__.py
      embeddings.py
      extractor.py
      gemini.py
      grounding.py
      heuristic.py
      schemas.py
      scoring.py
    api/
      __init__.py
      deps.py
      middleware.py
      routes/
        auth.py
        documents.py
        misc.py
        review.py
    core/
      __init__.py
      config.py
      errors.py
      logging.py
      ratelimit.py
      security.py
    db/
      __init__.py
      base.py
      models.py
    devtools/
      __init__.py
      synthetic.py
    domain/
      __init__.py
      dates.py
      matching.py
      money.py
      validation.py
    main.py
    processors/
      __init__.py
      classify.py
      files.py
      imaging.py
      layout.py
      ocr.py
      pdfpages.py
      spreadsheet.py
    repositories/
      __init__.py
    schemas/
      api.py
    services/
      __init__.py
      comparison.py
      corrections.py
      effective.py
      events.py
      extraction.py
      ingest.py
      pipeline.py
      runtime.py
      search.py
      stats.py
      storage.py
      users.py
      validation.py
    tasks/
      __init__.py
      celery_app.py
      dispatch.py
      tasks.py
  celerybeat-schedule.db
  constraints-tested.txt
  pyproject.toml
  scripts/
    e2e_real_stack.py
    evaluate.py
    gen_docs.py
    gen_reports.py
    perf_test.py
    ui_contract_check.py
  tests/
    __init__.py
    conftest.py
    test_ai_and_processors.py
    test_domain.py
    test_migrations.py
    test_pipeline_api.py
    test_recovery.py
    test_review_and_failures.py
    test_search_and_compare.py
    test_security_api.py
    test_smoke.py
docker/
  initdb/
    01-create-test-db.sql
docker-compose.yml
docs/
  AI_DISCLOSURE.md
  API_DOCUMENTATION.md
  ARCHITECTURE.md
  CHANGELOG.md
  CURRENT_PROJECT_STATE.md
  DATABASE_SCHEMA.md
  DEVELOPMENT_ROADMAP.md
  EVALUATION_REPORT.md
  HANDOFF_PROMPT.md
  IMPLEMENTATION_LOG.md
  NEXT_STEPS.md
  PROJECT_REQUIREMENTS.md
  SECURITY.md
  TESTING_REPORT.md
  coverage.json
  e2e_results.txt
  eval_results.json
  perf_results.json
  pytest_output.txt
  test_results.xml
  ui_contract_results.txt
frontend/
  .dockerignore
  .env.example
  Dockerfile
  app/
    (app)/
      compare/
        page.tsx
      dashboard/
        page.tsx
      documents/
        [id]/
          page.tsx
        page.tsx
      history/
        page.tsx
      layout.tsx
      search/
        page.tsx
      upload/
        page.tsx
    globals.css
    layout.tsx
    login/
      page.tsx
    page.tsx
  components/
    LogicalPanel.tsx
    PageViewer.tsx
    ui.tsx
  lib/
    api.ts
    auth.tsx
    format.ts
    hooks.ts
  next-env.d.ts
  next.config.mjs
  package-lock.json
  package.json
  postcss.config.mjs
  public/
    .gitkeep
  tailwind.config.ts
  tsconfig.json
scripts/
  test.ps1
```

## 7. How to run
Docker: `copy .env.example .env`; set `JWT_SECRET` (≥32 chars) and passwords; `docker compose up --build`; UI http://localhost:3000, API docs http://localhost:8000/docs; first admin = `ADMIN_EMAIL`/`ADMIN_PASSWORD`.
Backend dev: `cd backend; py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e ".[dev]"; ruff check .; ruff format --check .; mypy; pytest` (Linux/macOS tests start their own PostgreSQL via `pgserver`; on Windows run `.\scripts\test.ps1`, which uses the compose test DB `docint_test` — tests TRUNCATE tables, so a guard refuses DB names not ending in `test`).
Measurement scripts (Linux sandbox): `scripts/e2e_real_stack.py`, `scripts/perf_test.py`, `scripts/evaluate.py`, `scripts/ui_contract_check.py`, `scripts/gen_docs.py`, `scripts/gen_reports.py`.
Frontend: `cd frontend; npm ci; npm run typecheck; npm run build; npm run dev`.

## 8. Inspect these files first
`docs/CURRENT_PROJECT_STATE.md`, `docs/ARCHITECTURE.md`, `backend/app/services/pipeline.py` (stage logic + claims), `backend/app/tasks/tasks.py`, `backend/app/ai/{heuristic,grounding,scoring,gemini}.py`, `backend/app/domain/{validation,matching,money}.py`,
`backend/app/db/models.py`, `backend/tests/conftest.py`, `frontend/lib/api.ts`, `docs/TESTING_REPORT.md`, `docs/EVALUATION_REPORT.md`, `docs/NEXT_STEPS.md`.

## 9. Important technical decisions (do not silently undo)
Content-based file typing; page-level jobs with atomic claims + stalled-document reaper (not Celery chords); grounding drops ungrounded values; confidence is computed, not LLM-reported; corrections layered on versioned extractions;
`not_comparable` verdict for summary-vs-detail comparisons; repaired PDFs always go to review; sync SQLAlchemy; Postgres for relational+FTS+vectors; Decimal everywhere for money; synthetic data is the only labeled set so far.

## 10. EXACT NEXT TASK
**Run the stack for real and fix whatever breaks.** (1) `docker compose up --build` on the owner's Windows machine; diagnose each failure from the actual error text; (2) open the UI and click through login → upload → document detail (preview + highlight) → correct a field → approve → compare → search → history; fix UI bugs;
(3) run `scripts/test.ps1` and CI; (4) only then move to `docs/NEXT_STEPS.md` item 2 (real labeled invoices + Gemini evaluation). Update `docs/CURRENT_PROJECT_STATE.md`, `docs/IMPLEMENTATION_LOG.md`, `CHANGELOG.md`, and regenerate this prompt after each phase.

## 11. Rules you must follow
1. Never claim code works without running a test/command; if you cannot run something, say so plainly.
2. Never fabricate evaluation numbers; report measured results only and keep measured vs estimated separate. Say that synthetic results are an upper bound.
3. Give the exact file path for every file you create or change; provide complete working code (not fragments) unless a snippet is requested; explain dependencies, how to run, how to test, expected output, common errors. Give Windows PowerShell commands separately.
4. Work in small steps; explain what/why/how before implementing; do not silently modify working modules; keep backward compatibility; add tests for important behaviour; keep ruff + mypy --strict + pytest green.
5. Financial checks stay deterministic (`Decimal`); an LLM never decides validation or approval. Uploaded document text is untrusted data.
6. Never expose secrets; configuration via environment variables only. Treat free-tier LLMs as non-confidential.
7. Update the 14 documents in `docs/` so they reflect the code that really exists; regenerate generated docs with `scripts/gen_docs.py` and `scripts/gen_reports.py`.
8. If a requirement is unclear, ask one focused question instead of assuming.
