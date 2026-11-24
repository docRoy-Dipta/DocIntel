# Evaluation report

*Generated 2026-11-23 10:44 UTC by `scripts/gen_reports.py` from `docs/eval_results.json`, which is produced by `python scripts/evaluate.py`. Every number is **measured** by that script; nothing is estimated or typed by hand.*

## Read this first: what these numbers do and do not mean

- **Dataset:** synthetic, seeded (random.Random(2026)). Documents are generated programmatically with known ground truth, then (for the scanned conditions) rendered to images and degraded (rotation, blur, noise, JPEG compression). Synthetic invoices are **much easier** than real business documents: consistent layouts, clean fonts, one language, no stamps, handwriting, tables with merged cells or unusual layouts. Treat the accuracies as an upper bound for this extractor, not as a prediction for real data.
- **Extractor evaluated:** heuristic (rule-based); no LLM evaluated. The Gemini/LLM extractor has **not** been evaluated (no API key was available).
- **No real-world labeled dataset** was available. Building one (a few hundred real invoices with hand-checked labels) is the most important next step before trusting any number here.
- Environment: Python 3.12.3, 1 CPU, Linux-6.18.44-fc-v726-x86_64-with-glibc2.39.

## 1. Field-level extraction accuracy by input condition

Per invoice, each of 8 header fields is scored: *exact match* = correct, a wrong value counts as both a false positive and a false negative, a missing value is a false negative. Amounts are compared numerically, dates as ISO dates, text exactly.

| Condition | Docs | Invoices | Pages | Accuracy | Precision | Recall | F1 | Line-item F1 | Invoices fully correct |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| digital_pdf | 100 | 100 | 100 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100/100 |
| digital_pdf_bundles_multipage | 16 | 48 | 88 | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 48/48 |
| scanned_pdf_clean_150dpi | 24 | 24 | 24 | 99.5% | 100.0% | 99.5% | 99.7% | 100.0% | 23/24 |
| scanned_pdf_degraded | 24 | 24 | 24 | 100.0% | 100.0% | 100.0% | 100.0% | 93.5% | 24/24 |
| png_image | 12 | 12 | 12 | 96.9% | 100.0% | 96.9% | 98.4% | 95.2% | 10/12 |
| xlsx_spreadsheet | 5 | 40 | 10 | 100.0% | 100.0% | 100.0% | 100.0% | n/a | 40/40 |

Per-field accuracy:

| Condition | invoice_number | invoice_date | supplier_name | customer_name | subtotal | tax | total_amount | currency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| digital_pdf | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| digital_pdf_bundles_multipage | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| scanned_pdf_clean_150dpi | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 95.8% | 100.0% | 100.0% |
| scanned_pdf_degraded | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |
| png_image | 100.0% | 100.0% | 100.0% | 100.0% | 91.7% | 91.7% | 91.7% | 100.0% |
| xlsx_spreadsheet | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% | 100.0% |

Line-item F1 counts a predicted line as correct only if description **and** amount both match. It is not applicable to the summary-level spreadsheets (they carry no line items).

## 2. Does a wrong extraction reach a human? (manual-review flagging)

| Condition | Invoices with ≥1 wrong field | …of which flagged for review (review recall) | Correct invoices flagged anyway (extra work) |
|---|---:|---:|---:|
| digital_pdf | 0 | 0 (n/a) | 0 (0.0%) |
| digital_pdf_bundles_multipage | 0 | 0 (n/a) | 0 (0.0%) |
| scanned_pdf_clean_150dpi | 1 | 1 (100.0%) | 2 (8.7%) |
| scanned_pdf_degraded | 0 | 0 (n/a) | 5 (20.8%) |
| png_image | 2 | 2 (100.0%) | 2 (20.0%) |
| xlsx_spreadsheet | 0 | 0 (n/a) | 0 (0.0%) |

Review is triggered by validation errors/warnings, low confidence (OCR confidence × grounding × format checks), inferred values, dropped (ungrounded) values and damaged files.

## 3. Financial validation (deterministic rules)

Invoices were generated with one injected arithmetic error each. *Exact* means the set of error-level rules that fired equals the set expected for that error.

| Injected error | Invoices | Exactly detected | Extra error rules fired |
|---|---:|---:|---:|
| clean | 12 | 12 | 0 |
| total | 12 | 12 | 0 |
| subtotal | 12 | 12 | 0 |
| tax | 12 | 12 | 0 |
| line | 12 | 12 | 0 |

**Error-detection recall: 100.0%; false-alarm rate on clean invoices: 0.0%.** (The validator is plain Decimal arithmetic, so 100% here mostly confirms the *extraction* delivered the printed numbers correctly; the rules themselves are unit-tested individually in `tests/test_domain.py`.)

## 4. Cross-document discrepancy detection (PDF vs Excel)

Each pair is one digital PDF invoice and one spreadsheet row; one field was changed in the spreadsheet copy.

| Seeded discrepancy | Pairs | Detected as `mismatch` |
|---|---:|---:|
| none | 10 | n/a (control) |
| total | 10 | 10 |
| date | 10 | 10 |
| supplier | 10 | 10 |
| currency | 10 | 10 |

**Discrepancy recall: 100.0%. False-mismatch rate on the 360 unchanged fields: 0.0%.**

## 5. Processing time and success rate

Time per document is the full upload-to-final-status time in-process (eager Celery, one CPU), so it includes the database writes but no broker latency.

| Condition | Mean s / document | Median | Max | Mean s / page | Final statuses |
|---|---:|---:|---:|---:|---|
| digital_pdf | 0.059 | 0.052 | 0.447 | 0.059 | {'completed': 100} |
| digital_pdf_bundles_multipage | 0.168 | 0.152 | 0.261 | 0.031 | {'completed': 16} |
| scanned_pdf_clean_150dpi | 1.191 | 1.09 | 2.953 | 1.191 | {'completed': 21, 'needs_review': 3} |
| scanned_pdf_degraded | 1.625 | 1.609 | 1.962 | 1.625 | {'completed': 19, 'needs_review': 5} |
| png_image | 0.932 | 0.906 | 1.105 | 0.932 | {'needs_review': 4, 'completed': 8} |
| xlsx_spreadsheet | 0.205 | 0.195 | 0.246 | 0.103 | {'completed': 5} |

Across the 181 documents of the extraction set: **100.0% were processed without failure** (final statuses {'completed': 169, 'needs_review': 12}). `needs_review` is a *successful* outcome that routes work to a human.

## 6. OCR ablation: does deskew help?

Same rotated scans (±3–4°) processed with deskew on and off:

| Setting | Micro-F1 | Field accuracy | Line-item F1 |
|---|---:|---:|---:|
| deskew_on | 99.0% | 97.9% | 88.2% |
| deskew_off | 90.1% | 85.4% | 0.0% |

## Limitations and what is *not* measured

- Real invoices (layout variety, other languages, stamps, handwriting, photos taken with a phone).
- The LLM extractor, and therefore any comparison of heuristic vs LLM accuracy, cost or latency.
- Confidence calibration (whether 90% confidence really means 90% correct) — only the review-recall side effect is measured.
- Semantic-search quality: the default `hashing` embedder is lexical, and no relevance-judged query set exists. Search is tested for correctness (right document returned for targeted queries), not ranked quality.
- Scanned bundles of hundreds of pages (the 1,000-page test uses a digital PDF).
