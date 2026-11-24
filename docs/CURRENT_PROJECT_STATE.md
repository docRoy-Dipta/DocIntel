# Current project state

*Snapshot at the end of the "all modules first" build. Git: this build has not been committed by the assistant — run `git status` / `git log` in your clone. Last known branch plan: `phase-1-foundation`.*

## One-paragraph summary
Every module of the specification (A–H) is implemented. The backend (FastAPI + Celery + PostgreSQL/pgvector) is verified by 181 automated tests
(92.7% coverage), a real-Redis multi-process run that survives a worker `SIGKILL`, a 1,000-page performance run, and a labeled evaluation. The frontend (Next.js) type-checks strictly,
builds, serves every route, and its TypeScript types match the live API. **Not yet verified anywhere: Docker/Compose, the UI in a real browser, the Gemini extractor against the real API, real-world invoices.**

## Verified (measured — see TESTING_REPORT.md / EVALUATION_REPORT.md)
- Backend: `ruff check`, `ruff format --check`, `mypy` (strict, 72 files) clean; 181 tests pass, 0 skipped.
- Migration `0001`: upgrade ⇄ downgrade ⇄ upgrade work; `alembic check` shows models and migration identical.
- Pipeline for: digital PDF, scanned PDF, PNG, JPEG, multi-page TIFF, XLSX (summary + line layouts), XLS, CSV, multi-invoice bundles, duplicates, corrupt/truncated/encrypted files.
- Failure recovery: page failure → retry; transient LLM failure → retries → recovery; lost queue messages → reaper; **worker SIGKILL mid-OCR with real Redis → recovered**.
- 1,000-page PDF measured (time, memory, API latency) — numbers in TESTING_REPORT.md.
- Evaluation on a synthetic labeled set (extraction P/R/F1 by condition, validation, cross-document detection, review flagging, deskew ablation).
- Frontend: `tsc --noEmit` (strict + `noUncheckedIndexedAccess`), `next build`, all routes HTTP 200, CORS allow/deny behaviour, 20 TypeScript interfaces checked against real API JSON.

## Not verified / known limitations
| Area | Detail |
|---|---|
| Docker | Dockerfiles, `docker-compose.yml`, CI workflow written but **never executed** (no Docker in the dev sandbox). |
| Browser UI | Never opened in a browser: drag-and-drop, bounding-box overlay, inline editing are untested interactions. |
| Gemini | Request/response/error handling tested against a mocked HTTP transport only. Model name `gemini-2.5-flash` is a default to check in AI Studio. |
| Accuracy on real documents | Unknown. Synthetic results are an upper bound (see EVALUATION_REPORT.md). |
| Semantic search | Default hashing embedder is lexical; `sentence-transformers` path never run. |
| Windows | Test-suite on Windows needs the Docker test database (`scripts/test.ps1`); `pgserver` is not installed on Windows. |
| Language | English only (rules, keywords, OCR). |
| Corrections | Field corrections survive re-extraction; **line-item corrections do not** (they edit the current extraction's rows). No add/delete line item. |
| Splitting | Rule-based: invoices without a title + invoice-number line may be mis-split or treated as continuation pages. |
| Heuristic extractor | Assumes labelled English layouts (`Invoice No:`, `Bill To:`, `Subtotal`, `Total`); two-column header blocks and unusual layouts will need the LLM extractor. |
| Users | Created via API by an admin; no user-management UI, no password reset. |
| Scale | One-CPU measurements only; multi-worker scaling and concurrent-user load not measured. |
| Licence | None chosen; PyMuPDF is AGPL. |

## Folder structure
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

## How to run
See README.md. Short version: `copy .env.example .env` → set `JWT_SECRET` → `docker compose up --build` → <http://localhost:3000>.
Backend tests (Linux/macOS): `cd backend && pip install -e ".[dev]" && pytest`. Windows: `.\scripts\test.ps1`.

## Environment variables
All are documented in `.env.example` and `backend/app/core/config.py` (every setting has a default except `JWT_SECRET` in production and, when selected, `GEMINI_API_KEY`).
