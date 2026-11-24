# Development roadmap

The original plan (Phase 0) had phases 1–14 with approvals between them. At the owner's request the build was changed to
**"implement every module first, test afterwards"**, so the phases below were delivered together. The plan, and what became of each phase:

| Phase | Planned scope | Status |
|---|---|---|
| 0 | Requirements, architecture, roadmap | Done (approved) |
| 1 | Foundation: repo, tooling, Compose, FastAPI skeleton, DB + migrations, Celery skeleton, CI | Done (1.1 verified on the owner's machine path; the rest delivered with the full build) |
| 1b | Synthetic invoice generator | Done (`app/devtools/synthetic.py`) |
| 2 | Upload, validation, storage, duplicate detection | Done |
| 3 | Text acquisition: PDF, Excel, CSV | Done |
| 4 | OCR and preprocessing | Done (Tesseract; deskew ablation measured) |
| 5 | Classification and bundle splitting | Done (rule-based) |
| 6 | AI extraction: schema, grounding, confidence, provider interface, rate limiter | Done (Gemini path untested live) |
| 7 | Financial validation | Done |
| 8 | Review and corrections API, reprocessing | Done |
| 9 | Search: keyword, semantic, hybrid, filters | Done (hashing embedder default) |
| 10 | Cross-document verification | Done |
| 11 | Security and auth hardening | Done within the limits listed in SECURITY.md |
| 12 | Frontend | Done (not browser-tested) |
| 13 | Evaluation and performance | Done on synthetic data; real-data evaluation outstanding |
| 14 | Release polish | In progress — see NEXT_STEPS.md (first Docker run, license, real data) |

See [NEXT_STEPS.md](NEXT_STEPS.md) for the prioritised remaining work.
