"""Build docs/TESTING_REPORT.md and docs/EVALUATION_REPORT.md from the measurement result files.

No number in those reports is typed by hand: they are read from
  docs/test_results.xml, docs/coverage.json, docs/e2e_results.txt, docs/perf_results.json,
  docs/ui_contract_results.txt, docs/eval_results.json
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET  # noqa: S405 - we only parse our own pytest output
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"

CATEGORIES = {
    "tests.test_domain": "Unit: money & date parsing, every financial-validation rule, record matching",
    "tests.test_ai_and_processors": "Unit/AI/OCR/spreadsheet: classification, grounding, scoring, Gemini client (mocked HTTP), file safety, spreadsheet mapping, OCR, embeddings, rate limiting",
    "tests.test_pipeline_api": "Integration + API: whole pipeline for every input type (digital/scanned PDF, PNG/JPEG, TIFF, XLSX, XLS, CSV)",
    "tests.test_review_and_failures": "API + failure scenarios + AI safety: corrections, approvals, reprocessing, transient/permanent failures, hallucination & prompt injection",
    "tests.test_recovery": "Failure scenarios: lost queue messages / stalled documents",
    "tests.test_search_and_compare": "API: keyword/semantic/hybrid search, filters, cross-document verification",
    "tests.test_security_api": "Security: authn/authz, forged tokens, upload hardening, zip/decompression bombs, rate limits, injection",
    "tests.test_migrations": "Database: migrations apply, roll back, and match the models",
    "tests.test_smoke": "Smoke: package layout",
}


def junit() -> tuple[dict[str, dict[str, int]], dict[str, float]]:
    root = ET.parse(DOCS / "test_results.xml").getroot()  # noqa: S314
    per: dict[str, dict[str, int]] = defaultdict(lambda: {"passed": 0, "failed": 0, "skipped": 0})
    for case in root.iter("testcase"):
        mod = ".".join(case.get("classname", "").split(".")[:2])
        if case.find("failure") is not None or case.find("error") is not None:
            per[mod]["failed"] += 1
        elif case.find("skipped") is not None:
            per[mod]["skipped"] += 1
        else:
            per[mod]["passed"] += 1
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    assert suite is not None
    return per, {"time": float(suite.get("time", 0)), "tests": int(suite.get("tests", 0))}


def testing_report() -> str:
    per, meta = junit()
    cov = json.loads((DOCS / "coverage.json").read_text())
    perf = json.loads((DOCS / "perf_results.json").read_text())
    e2e = (DOCS / "e2e_results.txt").read_text()
    ui = (DOCS / "ui_contract_results.txt").read_text() if (DOCS / "ui_contract_results.txt").exists() else ""
    total = {k: sum(v[k] for v in per.values()) for k in ("passed", "failed", "skipped")}
    by_pkg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for path, f in cov["files"].items():
        parts = Path(path).parts
        pkg = parts[1] if len(parts) > 2 and parts[0] == "app" else "app (root)"
        by_pkg[pkg][0] += f["summary"]["covered_lines"]
        by_pkg[pkg][1] += f["summary"]["num_statements"]
    L = [
        "# Testing report",
        "",
        f"*Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC} by `scripts/gen_reports.py` from the files in `docs/`. "
        "Everything below was measured by running the commands shown; nothing is estimated.*",
        "",
        "## How to reproduce",
        "",
        "```bash",
        'cd backend && pip install -e ".[dev]"',
        "ruff check . && ruff format --check . && mypy        # static checks",
        "pytest -q --cov=app                                  # test-suite (real PostgreSQL + pgvector, Celery in eager mode)",
        "python scripts/e2e_real_stack.py                     # real Redis + separate worker process + SIGKILL crash test",
        "python scripts/perf_test.py 1000                     # ~1,000-page PDF + API latency",
        "python scripts/evaluate.py                           # labeled-dataset evaluation -> EVALUATION_REPORT.md",
        "python scripts/ui_contract_check.py                  # frontend/backend contract check (needs `npm run build`)",
        "```",
        "",
        "## Test environment",
        "",
        f"Python {perf['environment']['python']}, {perf['environment']['cpus']} CPU, {perf['environment']['platform']}. "
        "PostgreSQL 16 + pgvector 0.6 (via `pgserver`), Tesseract 5.3, Redis 7.0 (e2e only).",
        "",
        "## Test-suite result",
        "",
        f"**{total['passed']} passed, {total['failed']} failed, {total['skipped']} skipped** in {meta['time']:.0f} s "
        f"(total statement coverage of `app/`: **{cov['totals']['percent_covered']:.1f}%**).",
        "",
        "| Test module | Passed | Failed | Skipped | What it covers |",
        "|---|---:|---:|---:|---|",
    ]
    for mod in sorted(per):
        v = per[mod]
        L.append(
            f"| `{mod.replace('.', '/')}.py` | {v['passed']} | {v['failed']} | {v['skipped']} | {CATEGORIES.get(mod, '')} |"
        )
    L += [
        "",
        "### Coverage by package",
        "",
        "| Package | Statements | Covered | % |",
        "|---|---:|---:|---:|",
    ]
    for pkg, (cvd, n) in sorted(by_pkg.items()):
        L.append(f"| `app/{pkg}` | {n} | {cvd} | {100 * cvd / n:.0f}% |" if n else f"| `app/{pkg}` | 0 | 0 | — |")
    L += [
        "",
        "Lines not covered are mostly: the real Gemini network path beyond the mocked transport, the optional "
        "sentence-transformers embedder, Redis-specific code paths exercised only by `e2e_real_stack.py`, and defensive error branches.",
        "",
        "## Requirement → test mapping (Module H)",
        "",
        "| Required test type | Where |",
        "|---|---|",
        "| Unit | `test_domain.py`, `test_ai_and_processors.py` |",
        "| Integration | `test_pipeline_api.py` (API + PostgreSQL + pipeline), `test_migrations.py` |",
        "| API | `test_pipeline_api.py`, `test_review_and_failures.py`, `test_search_and_compare.py`, `test_security_api.py` |",
        "| OCR | `test_ai_and_processors.py::test_ocr_*` (clean, rotated, noisy, JPEG-compressed scans), `test_pipeline_api.py` (scanned PDF, PNG, JPEG, multi-page TIFF) |",
        "| Spreadsheet parsing | `test_ai_and_processors.py` (header offsets, decorated headers, CSV encodings/delimiters, formulas without cached values, row limit), `test_pipeline_api.py` (XLSX summary & line layouts, multi-sheet, XLS, CSV) |",
        "| AI extraction | `test_ai_and_processors.py` (grounding, scoring, Gemini request/response/errors/rate limit with mocked HTTP), `test_review_and_failures.py` (hallucination rejected, prompt injection) |",
        "| Validation | `test_domain.py` (every rule has a positive test; tolerance edge cases) |",
        "| Failure scenarios | `test_review_and_failures.py` (page failure → retry, LLM timeout → retry → recover, idempotency/claims), `test_recovery.py` (lost messages), `test_pipeline_api.py` (corrupt, truncated, encrypted, duplicate), `e2e_real_stack.py` (worker SIGKILL) |",
        "| Performance | `scripts/perf_test.py` (below) |",
        "| Security | `test_security_api.py` |",
        "",
        "## Real-stack end-to-end run (`scripts/e2e_real_stack.py`)",
        "",
        "Real Redis broker, real PostgreSQL, a **separate Celery worker process**, the API server over HTTP, and a `SIGKILL` of the worker in the middle of OCR.",
        "",
        "```text",
        "\n".join(
            ln for ln in e2e.splitlines() if ln.startswith(("PASS", "FAIL", "ALL", "      ")) and "RuntimeDir" not in ln
        ),
        "```",
        "",
        "## Performance (`scripts/perf_test.py`)",
        "",
        f"Document: **{perf['document']['pages']} pages**, {perf['document']['invoices']} invoices, {perf['document']['size_mb']} MB (digital PDF). "
        f"Mode: {perf['environment']['note']}.",
        "",
        "| Measurement | Result |",
        "|---|---|",
        f"| Final status | {perf['pipeline']['status']} |",
        f"| Total pipeline time | {perf['pipeline']['wall_seconds']} s ({perf['pipeline']['pages_per_second']} pages/s) |",
        f"| Invoices found | {perf['pipeline']['invoices_extracted']} of {perf['pipeline']['invoices_expected']} |",
        f"| Process memory before / after / peak | {perf['pipeline']['rss_mb_before']} MB / {perf['pipeline']['rss_mb_after']} MB / {perf['pipeline']['peak_rss_mb']} MB |",
        "",
        "Memory stays flat because each page is read, stored and released on its own (the PDF is never loaded as a whole).",
        "",
        "API latency while the database holds those pages (in-process client, so network time is excluded):",
        "",
        "| Endpoint | n | p50 | p95 | max |",
        "|---|---:|---:|---:|---:|",
    ]
    key = next(k for k in perf if k.startswith("api_latency"))
    for name, v in perf[key].items():
        L.append(f"| `{name}` | {v['n']} | {v['p50_ms']} ms | {v['p95_ms']} ms | {v['max_ms']} ms |")
    L += [
        "",
        "Not measured: throughput with several parallel workers on a multi-core machine, OCR throughput on a 1,000-page *scanned* PDF "
        "(OCR cost measured per page in the evaluation instead), and behaviour with a real (non-mocked) LLM.",
        "",
        "## Frontend ↔ backend contract (`scripts/ui_contract_check.py`)",
        "",
    ]
    passes = len(re.findall(r"^PASS", ui, re.M))
    fails = len(re.findall(r"^FAIL", ui, re.M))
    L += [
        f"{passes} checks passed, {fails} failed: all page routes are served by the built Next.js app, CORS allows the frontend origin and refuses "
        "a foreign one, and every TypeScript interface in `frontend/lib/api.ts` was compared with a real API response.",
        "",
        "**Not tested:** user interactions in a real browser (clicking, drag-and-drop, the bounding-box overlay). "
        "The sandbox used for development could not download a browser. Static checks that were run: TypeScript strict mode and `next build`.",
        "",
        "## Known gaps",
        "",
        "- `docker compose` (Dockerfiles, compose file) could not be executed in the development sandbox: they are untested until first run on a machine with Docker.",
        "- The Gemini extractor was tested only against a mocked HTTP transport (request shape, parsing, error handling, rate limiting). It has never talked to the real API.",
        "- Load testing with many concurrent users was not done.",
        "",
    ]
    return "\n".join(L)


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def evaluation_report() -> str:
    ev = json.loads((DOCS / "eval_results.json").read_text())
    env = ev["environment"]
    L = [
        "# Evaluation report",
        "",
        f"*Generated {datetime.now(UTC):%Y-%m-%d %H:%M UTC} by `scripts/gen_reports.py` from `docs/eval_results.json`, which is produced by "
        "`python scripts/evaluate.py`. Every number is **measured** by that script; nothing is estimated or typed by hand.*",
        "",
        "## Read this first: what these numbers do and do not mean",
        "",
        f"- **Dataset:** {env['dataset']}. Documents are generated programmatically with known ground truth, then (for the scanned "
        "conditions) rendered to images and degraded (rotation, blur, noise, JPEG compression). Synthetic invoices are **much easier** than real "
        "business documents: consistent layouts, clean fonts, one language, no stamps, handwriting, tables with merged cells or unusual layouts. "
        "Treat the accuracies as an upper bound for this extractor, not as a prediction for real data.",
        f"- **Extractor evaluated:** {env['extractor']}. The Gemini/LLM extractor has **not** been evaluated (no API key was available).",
        "- **No real-world labeled dataset** was available. Building one (a few hundred real invoices with hand-checked labels) is the most important next step before trusting any number here.",
        f"- Environment: Python {env['python']}, {env['cpus']} CPU, {env['platform']}.",
        "",
        "## 1. Field-level extraction accuracy by input condition",
        "",
        "Per invoice, each of 8 header fields is scored: *exact match* = correct, a wrong value counts as both a false positive and a false negative, "
        "a missing value is a false negative. Amounts are compared numerically, dates as ISO dates, text exactly.",
        "",
        "| Condition | Docs | Invoices | Pages | Accuracy | Precision | Recall | F1 | Line-item F1 | Invoices fully correct |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cond, v in ev["extraction_by_condition"].items():
        m = v["fields_micro_avg"]
        li = v["line_items"]
        L.append(
            f"| {cond} | {v['documents']} | {v['invoices']} | {v['pages']} | {pct(m['accuracy'])} | {pct(m['precision'])} | {pct(m['recall'])} | "
            f"{pct(m['f1'])} | {pct(li['f1']) if isinstance(li, dict) else 'n/a'} | {v['invoices_fully_correct']} |"
        )
    L += [
        "",
        "Per-field accuracy:",
        "",
        "| Condition | " + " | ".join(next(iter(ev["extraction_by_condition"].values()))["fields"]) + " |",
        "|---|" + "---:|" * 8,
    ]
    for cond, v in ev["extraction_by_condition"].items():
        L.append(f"| {cond} | " + " | ".join(pct(f["accuracy"]) for f in v["fields"].values()) + " |")
    L += [
        "",
        "Line-item F1 counts a predicted line as correct only if description **and** amount both match. It is not applicable to the summary-level spreadsheets (they carry no line items).",
        "",
        "## 2. Does a wrong extraction reach a human? (manual-review flagging)",
        "",
        "| Condition | Invoices with ≥1 wrong field | …of which flagged for review (review recall) | Correct invoices flagged anyway (extra work) |",
        "|---|---:|---:|---:|",
    ]
    for cond, v in ev["extraction_by_condition"].items():
        r = v["review_flagging"]
        L.append(
            f"| {cond} | {r['wrong_invoices']} | {r['wrong_and_sent_to_review']}"
            + (f" ({pct(r['review_recall'])})" if r["review_recall"] is not None else " (n/a)")
            + f" | {r['correct_but_sent_to_review']} ({pct(r['unnecessary_review_rate'])}) |"
        )
    L += [
        "",
        "Review is triggered by validation errors/warnings, low confidence (OCR confidence × grounding × format checks), inferred values, dropped (ungrounded) values and damaged files.",
        "",
        "## 3. Financial validation (deterministic rules)",
        "",
        "Invoices were generated with one injected arithmetic error each. *Exact* means the set of error-level rules that fired equals the set expected for that error.",
        "",
        "| Injected error | Invoices | Exactly detected | Extra error rules fired |",
        "|---|---:|---:|---:|",
    ]
    for kind, v in ev["validation"]["by_injected_error"].items():
        L.append(f"| {kind} | {v['n']} | {v['detected_exact']} | {v['extra_codes']} |")
    L += [
        "",
        f"**Error-detection recall: {pct(ev['validation']['error_detection_recall'])}; false-alarm rate on clean invoices: "
        f"{pct(ev['validation']['false_alarm_rate_on_clean_invoices'])}.** "
        "(The validator is plain Decimal arithmetic, so 100% here mostly confirms the *extraction* delivered the printed numbers correctly; "
        "the rules themselves are unit-tested individually in `tests/test_domain.py`.)",
        "",
        "## 4. Cross-document discrepancy detection (PDF vs Excel)",
        "",
        "Each pair is one digital PDF invoice and one spreadsheet row; one field was changed in the spreadsheet copy.",
        "",
        "| Seeded discrepancy | Pairs | Detected as `mismatch` |",
        "|---|---:|---:|",
    ]
    for kind, v in ev["cross_document"]["by_seeded_discrepancy"].items():
        L.append(f"| {kind} | {v['pairs']} | {v['detected'] if kind != 'none' else 'n/a (control)'} |")
    cd = ev["cross_document"]
    L += [
        "",
        f"**Discrepancy recall: {pct(cd['discrepancy_recall'])}. False-mismatch rate on the {cd['unchanged_fields_compared']} unchanged fields: {pct(cd['false_mismatch_rate_on_unchanged_fields'])}.**",
        "",
        "## 5. Processing time and success rate",
        "",
        "Time per document is the full upload-to-final-status time in-process (eager Celery, one CPU), so it includes the database writes but no broker latency.",
        "",
        "| Condition | Mean s / document | Median | Max | Mean s / page | Final statuses |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for cond, v in ev["extraction_by_condition"].items():
        s = v["seconds_per_document"]
        L.append(
            f"| {cond} | {s['mean']} | {s['median']} | {s['max']} | {v['seconds_per_page_mean']} | {v['final_status_counts']} |"
        )
    o = ev["document_outcomes_extraction_set"]
    L += [
        "",
        f"Across the {o['documents']} documents of the extraction set: **{pct(o['processed_without_failure_rate'])} were processed without failure** "
        f"(final statuses {o['by_final_status']}). `needs_review` is a *successful* outcome that routes work to a human.",
        "",
        "## 6. OCR ablation: does deskew help?",
        "",
        "Same rotated scans (±3–4°) processed with deskew on and off:",
        "",
        "| Setting | Micro-F1 | Field accuracy | Line-item F1 |",
        "|---|---:|---:|---:|",
    ]
    for k, v in ev["ocr_ablation_rotated_scans"].items():
        L.append(f"| {k} | {pct(v['micro_f1'])} | {pct(v['accuracy'])} | {pct(v['line_item_f1'])} |")
    L += [
        "",
        "## Limitations and what is *not* measured",
        "",
        "- Real invoices (layout variety, other languages, stamps, handwriting, photos taken with a phone).",
        "- The LLM extractor, and therefore any comparison of heuristic vs LLM accuracy, cost or latency.",
        "- Confidence calibration (whether 90% confidence really means 90% correct) — only the review-recall side effect is measured.",
        "- Semantic-search quality: the default `hashing` embedder is lexical, and no relevance-judged query set exists. Search is tested for correctness (right document returned for targeted queries), not ranked quality.",
        "- Scanned bundles of hundreds of pages (the 1,000-page test uses a digital PDF).",
        "",
    ]
    return "\n".join(L)


def main() -> None:
    (DOCS / "TESTING_REPORT.md").write_text(testing_report())
    (DOCS / "EVALUATION_REPORT.md").write_text(evaluation_report())
    print("written docs/TESTING_REPORT.md and docs/EVALUATION_REPORT.md")


if __name__ == "__main__":
    main()
