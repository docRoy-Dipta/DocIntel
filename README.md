# AI-Powered Document Intelligence System

Upload invoices and receipts (PDF, scans, photos, Excel, CSV), extract structured data with evidence, check the arithmetic
deterministically, compare documents against each other, and search everything — through a REST API and a web interface.

> **Status:** all modules of the original specification are implemented and tested in a development sandbox
> (181 automated tests, 92.7% line coverage of the backend). **Docker Compose and the browser UI have not yet been run
> on a real machine** — see [CURRENT_PROJECT_STATE.md](docs/CURRENT_PROJECT_STATE.md) for exactly what is verified and what is not.

## What it does

| Capability | How |
|---|---|
| Inputs | PDF (digital & scanned, multi-page, up to ~1,000+ pages), PNG, JPEG, TIFF (multi-page), XLSX, XLS, CSV |
| Safe intake | Content-based type detection (magic bytes), size limits, streaming SHA-256, duplicate detection, corruption/encryption/zip-bomb checks |
| Text | Digital text layer via PyMuPDF; OCR (Tesseract) with deskew for scans; spreadsheets via header detection + column mapping |
| Bundles | A 1,000-page PDF is treated as *many* invoices: pages are classified and split into logical documents |
| Extraction | Invoice number/date, supplier, customer, subtotal, tax, total, currency, line items — each with raw text, page, bounding box, confidence, and *extracted vs inferred* |
| Anti-hallucination | Every value must be found in the source text (**grounding**); invented values are dropped and flagged |
| Validation | Deterministic `Decimal` arithmetic: required fields, line math, subtotal, tax, total, currency consistency, dates, duplicate invoices |
| Review | Uncertain results go to a review queue; corrections are layered on top (never overwrite) and re-validate instantly |
| Verification | PDF↔PDF, PDF↔Excel, invoice↔receipt with per-field verdicts and evidence (file, page, bbox or sheet+cell) |
| Search | PostgreSQL full-text, pgvector semantic, and hybrid (rank fusion) + structured filters |
| Background work | Celery + Redis, page-level jobs, idempotent stages, retries, stalled-job recovery |

## Architecture in one picture

```
 Browser (Next.js) ──HTTP/JSON──▶ FastAPI ──▶ PostgreSQL + pgvector
                                     │  enqueue                ▲
                                     ▼                         │ state, results, search
                                   Redis ──▶ Celery workers ───┘
                                             queues: parse · ocr · llm
                                             (+ beat: re-queues stalled documents)
```

Details and the reasoning behind each decision: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start (Docker — recommended)

Requires Docker Desktop (on Windows: WSL 2 backend).

```powershell
copy .env.example .env
# edit .env: set JWT_SECRET (>= 32 random characters) and the admin/db passwords. Generate a secret with:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"
docker compose up --build
```

Then open <http://localhost:3000> and sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD` from `.env`.
API docs: <http://localhost:8000/docs>. Create more users (admin only) with `POST /api/v1/users`.

### Free-tier LLM (optional)

By default `LLM_PROVIDER=heuristic`: a free, offline, rule-based extractor. To use Gemini's free tier set
`LLM_PROVIDER=gemini`, `GEMINI_API_KEY=...` in `.env`. Free tiers are rate-limited (the app throttles itself with
`LLM_REQUESTS_PER_MINUTE`) and may use prompts for model training — **do not send confidential documents** to a free tier.
The Gemini integration is tested only against a mocked HTTP server; see the limitations in `CURRENT_PROJECT_STATE.md`.

## Development setup (Windows PowerShell)

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
ruff check . ; ruff format --check . ; mypy
cd ..
.\scripts\test.ps1          # starts the docker test database and runs pytest
```

Frontend: `cd frontend; npm ci; npm run dev` (needs the API on `NEXT_PUBLIC_API_URL`, default `http://localhost:8000`).

Running the tests on Linux/macOS needs no Docker: the suite starts its own throw-away PostgreSQL via the `pgserver` package.
Tesseract must be installed for the OCR tests (they are skipped otherwise).

## Repository map

```
backend/app/
  api/          HTTP routes, auth dependencies, middleware (rate limit, security headers)
  core/         settings, logging, security (scrypt, JWT), errors, rate limiter
  db/           SQLAlchemy models + session
  domain/       PURE business logic: money, dates, validation rules, matching  (no I/O)
  processors/   file detection, PDF/image/OCR, spreadsheets, classification & splitting
  ai/           extractors (heuristic, Gemini), grounding, confidence scoring, embeddings
  services/     pipeline stages, extraction, validation, corrections, comparison, search, stats
  tasks/        Celery app, tasks, dispatch
  devtools/     synthetic invoice generator (tests & evaluation)
backend/alembic/   migrations        backend/tests/   test-suite       backend/scripts/   e2e, perf, evaluation, doc generators
frontend/          Next.js + TypeScript + Tailwind UI
docs/              requirements, architecture, schema, API, reports, handoff
```

## Documentation

| Document | Contents |
|---|---|
| [PROJECT_REQUIREMENTS](docs/PROJECT_REQUIREMENTS.md) | Requirements and how each is satisfied |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Components, workflow, decisions and trade-offs |
| [DATABASE_SCHEMA](docs/DATABASE_SCHEMA.md) · [API_DOCUMENTATION](docs/API_DOCUMENTATION.md) | Generated from the code |
| [TESTING_REPORT](docs/TESTING_REPORT.md) · [EVALUATION_REPORT](docs/EVALUATION_REPORT.md) | **Measured** results (and honest limitations) |
| [SECURITY](docs/SECURITY.md) · [AI_DISCLOSURE](docs/AI_DISCLOSURE.md) | Threat model; how AI was and is used |
| [CURRENT_PROJECT_STATE](docs/CURRENT_PROJECT_STATE.md) · [NEXT_STEPS](docs/NEXT_STEPS.md) · [HANDOFF_PROMPT](docs/HANDOFF_PROMPT.md) | Where things stand and what to do next |
| [DEVELOPMENT_ROADMAP](docs/DEVELOPMENT_ROADMAP.md) · [IMPLEMENTATION_LOG](docs/IMPLEMENTATION_LOG.md) · [CHANGELOG](CHANGELOG.md) | History |

## Licensing note

PyMuPDF (the PDF engine) is licensed **AGPL-3.0** (or commercially from Artifex). If you distribute this software or offer it as a network
service, that license applies to your combined work. Decide on a license for this repository with that in mind; none has been added yet.
