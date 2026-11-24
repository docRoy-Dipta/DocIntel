"""Measured evaluation on a labeled synthetic dataset. Every number is computed here, never typed by hand.

What is measured (extractor under test: the rule-based HeuristicExtractor; no LLM is evaluated):
  1. Field-level extraction accuracy / precision / recall / F1 per input condition
  2. Review flagging: are wrong extractions routed to a human?
  3. Financial validation: detection of injected arithmetic errors and false alarms on clean invoices
  4. Cross-document discrepancy detection (PDF vs Excel with seeded discrepancies)
  5. Processing time and document success / failure rate
  6. OCR ablation: deskew on/off on rotated scans
Run:  python scripts/evaluate.py [--quick]      Output: docs/eval_results.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

FIELDS = [
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total_amount",
    "currency",
]


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    n: int = 0

    def add(self, truth: str | None, pred: str | None, numeric: bool) -> None:
        self.n += 1
        if pred is None:
            self.fn += 1
        elif same(truth, pred, numeric):
            self.tp += 1
        else:
            self.fp += 1
            self.fn += 1

    def report(self) -> dict[str, float | int]:
        p = self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0
        r = self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        return {
            "n": self.n,
            "accuracy": round(self.tp / self.n, 4) if self.n else 0.0,
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
        }


def same(truth: str | None, pred: str | None, numeric: bool) -> bool:
    if truth is None or pred is None:
        return truth == pred
    if numeric:
        return Decimal(truth) == Decimal(pred)
    return truth == pred


@dataclass
class ConditionResult:
    docs: int = 0
    invoices: int = 0
    fields: dict[str, Counts] = field(default_factory=lambda: {f: Counts() for f in FIELDS})
    lines: Counts = field(default_factory=Counts)
    seconds: list[float] = field(default_factory=list)
    pages: int = 0
    statuses: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    wrong_invoices: int = 0
    wrong_and_flagged: int = 0
    right_invoices: int = 0
    right_and_flagged: int = 0
    unmatched_truth: int = 0

    def score_invoice(self, truth: dict[str, Any], logical: dict[str, Any], has_lines: bool = True) -> None:
        got = {f["name"]: f["value"] for f in logical["fields"]}
        bad = False
        for name in FIELDS:
            self.fields[name].add(truth[name], got[name], numeric=name in ("subtotal", "tax", "total_amount"))
            if not same(truth[name], got[name], name in ("subtotal", "tax", "total_amount")):
                bad = True
        t_lines = [(li["description"], Decimal(li["amount"])) for li in truth["line_items"]] if has_lines else []
        p_lines = (
            [(li["description"], Decimal(li["amount"])) for li in logical["line_items"] if li["amount"] is not None]
            if has_lines
            else []
        )
        remaining = list(p_lines)
        for tl in t_lines:
            self.lines.n += 1
            if tl in remaining:
                remaining.remove(tl)
                self.lines.tp += 1
            else:
                self.lines.fn += 1
        self.lines.fp += len(remaining)
        self.invoices += 1
        flagged = logical["needs_review"]
        if bad:
            self.wrong_invoices += 1
            self.wrong_and_flagged += flagged
        else:
            self.right_invoices += 1
            self.right_and_flagged += flagged

    def report(self) -> dict[str, Any]:
        micro = Counts()
        for c in self.fields.values():
            micro.tp, micro.fp, micro.fn, micro.n = micro.tp + c.tp, micro.fp + c.fp, micro.fn + c.fn, micro.n + c.n
        return {
            "documents": self.docs,
            "invoices": self.invoices,
            "pages": self.pages,
            "fields": {k: v.report() for k, v in self.fields.items()},
            "fields_micro_avg": micro.report(),
            "line_items": self.lines.report() if self.lines.n else "not applicable (summary-level spreadsheet)",
            "invoices_fully_correct": f"{self.right_invoices}/{self.invoices}",
            "seconds_per_document": {
                "mean": round(statistics.mean(self.seconds), 3) if self.seconds else None,
                "median": round(statistics.median(self.seconds), 3) if self.seconds else None,
                "max": round(max(self.seconds), 3) if self.seconds else None,
            },
            "seconds_per_page_mean": round(sum(self.seconds) / self.pages, 3) if self.pages else None,
            "final_status_counts": dict(self.statuses),
            "review_flagging": {
                "wrong_invoices": self.wrong_invoices,
                "wrong_and_sent_to_review": self.wrong_and_flagged,
                "review_recall": round(self.wrong_and_flagged / self.wrong_invoices, 4)
                if self.wrong_invoices
                else None,
                "correct_but_sent_to_review": self.right_and_flagged,
                "unnecessary_review_rate": round(self.right_and_flagged / self.right_invoices, 4)
                if self.right_invoices
                else None,
            },
        }


class Harness:
    def __init__(self) -> None:
        import pgserver

        self.tmp = Path(tempfile.mkdtemp(prefix="docint-eval-"))
        pg = pgserver.get_server(self.tmp / "pg", cleanup_mode="stop")
        os.environ.update(
            {
                "DATABASE_URL": pg.get_uri().replace("postgresql://", "postgresql+psycopg://"),
                "STORAGE_DIR": str(self.tmp / "storage"),
                "APP_ENV": "test",
                "CELERY_EAGER": "true",
                "LOG_LEVEL": "ERROR",
                "LOG_JSON": "false",
                "JWT_SECRET": "eval-only-secret-0123456789-0123456789",
                "ADMIN_EMAIL": "admin@example.com",
                "ADMIN_PASSWORD": "eval-admin-password",
                "RATE_LIMIT_PER_MINUTE": "1000000",
            }
        )
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, check=True, capture_output=True
        )
        from fastapi.testclient import TestClient

        from app.main import create_app
        from app.tasks.celery_app import celery_app

        celery_app.conf.task_always_eager = True
        self.client = TestClient(create_app())
        self.client.__enter__()
        token = self.client.post(
            "/api/v1/auth/login", json={"email": "admin@example.com", "password": "eval-admin-password"}
        ).json()["access_token"]
        self.h = {"Authorization": f"Bearer {token}"}

    def upload(self, name: str, data: bytes) -> tuple[str, float]:
        t = time.perf_counter()
        r = self.client.post("/api/v1/documents", headers=self.h, files=[("files", (name, data))])
        elapsed = time.perf_counter() - t
        res = r.json()["results"][0]
        assert res["status"] in ("accepted", "duplicate"), res
        return str(res["document_id"]), elapsed

    def invoices(self, doc_id: str) -> list[dict[str, Any]]:
        r = self.client.get(f"/api/v1/documents/{doc_id}/extractions", headers=self.h)
        return [x for x in r.json() if x["doc_type"] == "invoice"]

    def status(self, doc_id: str) -> dict[str, Any]:
        return self.client.get(f"/api/v1/documents/{doc_id}/status", headers=self.h).json()  # type: ignore[no-any-return]


def run_condition(
    h: Harness, name: str, items: list[tuple[str, bytes, list[Any]]], has_lines: bool = True
) -> ConditionResult:
    res = ConditionResult()
    for filename, data, invs in items:
        doc_id, elapsed = h.upload(filename, data)
        st = h.status(doc_id)
        res.docs += 1
        res.pages += st["page_count"]
        res.seconds.append(elapsed)
        res.statuses[st["status"]] += 1
        logicals = h.invoices(doc_id)
        for i, inv in enumerate(invs):
            if i < len(logicals):
                res.score_invoice(inv.truth(), logicals[i], has_lines)
            else:
                res.unmatched_truth += 1
        print(f"  [{name}] {res.docs}/{len(items)}", end="\r")
    print(f"  [{name}] done: {res.docs} documents, {res.invoices} invoices")
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    q = ap.parse_args().quick
    n_dig, n_scan, n_png, n_multi, n_xlsx, n_val, n_cmp, n_abl = (
        (20, 6, 4, 4, 8, 10, 6, 6) if q else (100, 24, 12, 16, 40, 60, 10, 24)
    )

    from app.core.config import get_settings
    from app.devtools import synthetic as syn
    from app.services.runtime import reset_runtime

    rng = random.Random(2026)
    h = Harness()
    out: dict[str, Any] = {
        "environment": {
            "python": platform.python_version(),
            "cpus": os.cpu_count(),
            "platform": platform.platform(),
            "extractor": "heuristic (rule-based); no LLM evaluated",
            "dataset": "synthetic, seeded (random.Random(2026))",
            "quick_mode": q,
        }
    }
    idx = iter(range(10**6))

    def inv() -> Any:
        return syn.random_invoice(rng, next(idx))

    conditions: dict[str, ConditionResult] = {}
    print("1) extraction accuracy by input condition")
    d = [inv() for _ in range(n_dig)]
    conditions["digital_pdf"] = run_condition(
        h, "digital_pdf", [(f"d{i}.pdf", syn.make_pdf([x]), [x]) for i, x in enumerate(d)]
    )
    b = [[inv() for _ in range(3)] for _ in range(n_multi)]
    for grp in b:
        grp[1].items = grp[1].items * 3
        grp[1].items_per_page = 4
    conditions["digital_pdf_bundles_multipage"] = run_condition(
        h, "bundles", [(f"b{i}.pdf", syn.make_pdf(g), g) for i, g in enumerate(b)]
    )
    s = [inv() for _ in range(n_scan)]
    conditions["scanned_pdf_clean_150dpi"] = run_condition(
        h, "scan_clean", [(f"s{i}.pdf", syn.make_scanned_pdf(syn.make_pdf([x]), 150), [x]) for i, x in enumerate(s)]
    )
    sd = [inv() for _ in range(n_scan)]
    deg = [dict(rotate=rng.uniform(-3, 3), blur=0.8, noise=12, jpeg_quality=50) for _ in sd]
    conditions["scanned_pdf_degraded"] = run_condition(
        h,
        "scan_degraded",
        [
            (f"sd{i}.pdf", syn.make_scanned_pdf(syn.make_pdf([x]), 150, **k), [x])
            for i, (x, k) in enumerate(zip(sd, deg, strict=True))
        ],
    )
    p = [inv() for _ in range(n_png)]
    conditions["png_image"] = run_condition(
        h, "png", [(f"p{i}.png", syn.make_image(syn.make_pdf([x]), "PNG", dpi=150), [x]) for i, x in enumerate(p)]
    )
    x_inv = [inv() for _ in range(n_xlsx)]
    conditions["xlsx_spreadsheet"] = run_condition(
        h,
        "xlsx",
        [(f"x{i}.xlsx", syn.make_xlsx(x_inv[i : i + 8], "summary"), x_inv[i : i + 8]) for i in range(0, n_xlsx, 8)],
        has_lines=False,
    )
    out["extraction_by_condition"] = {k: v.report() for k, v in conditions.items()}

    print("2) financial validation: injected errors")
    kinds = ["clean", "total", "subtotal", "tax", "line"]
    vstats: dict[str, dict[str, int]] = {
        k: {"n": 0, "detected_exact": 0, "detected_any": 0, "extra_codes": 0} for k in kinds
    }
    for i in range(n_val):
        kind = kinds[i % len(kinds)]
        x = inv()
        if kind == "total":
            x.total_override = x.subtotal + x.tax + Decimal(rng.randint(1, 80))
        elif kind == "subtotal":
            x.subtotal_override = sum((a for *_, a in x.lines), Decimal(0)) + Decimal(rng.randint(1, 80))
        elif kind == "tax":
            x.tax_override = (x.subtotal * x.tax_rate / 100).quantize(Decimal("0.01")) + Decimal(rng.randint(1, 40))
        elif kind == "line":
            x.line_amount_overrides = {0: x.lines[0][3] + Decimal(rng.randint(1, 60))}
        doc_id, _ = h.upload(f"v{i}.pdf", syn.make_pdf([x]))
        (logical,) = h.invoices(doc_id)
        fired = {v["rule_code"] for v in logical["validation"] if v["severity"] == "error"}
        want = x.expected_error_codes
        st = vstats[kind]
        st["n"] += 1
        st["detected_exact"] += fired == want
        st["detected_any"] += bool(fired & want) if want else not fired
        st["extra_codes"] += len(fired - want)
    errs = sum(v["n"] for k, v in vstats.items() if k != "clean")
    out["validation"] = {
        "by_injected_error": vstats,
        "error_detection_recall": round(sum(v["detected_any"] for k, v in vstats.items() if k != "clean") / errs, 4),
        "false_alarm_rate_on_clean_invoices": round(1 - vstats["clean"]["detected_exact"] / vstats["clean"]["n"], 4),
        "note": "detected_exact = the set of error rules that fired equals the set expected for the injected error",
    }

    print("3) cross-document verification (PDF vs Excel, seeded discrepancies)")
    seeds = ["none", "total", "date", "supplier", "currency"]
    cmp_stats = {k: {"pairs": 0, "detected": 0} for k in seeds}
    clean_fields = 0
    false_flags = 0
    for i in range(n_cmp * len(seeds)):
        kind = seeds[i % len(seeds)]
        a = inv()
        b2 = copy.deepcopy(a)
        target = {
            "total": "total_amount",
            "date": "invoice_date",
            "supplier": "supplier_name",
            "currency": "currency",
        }.get(kind)
        if kind == "total":
            b2.total_override = a.total + Decimal(rng.randint(1, 50))
        elif kind == "date":
            b2.invoice_date = a.invoice_date + timedelta(days=rng.randint(1, 30))
        elif kind == "supplier":
            b2.supplier = rng.choice(
                [s_ for s_ in syn.SUPPLIERS if s_ != a.supplier and s_.split()[0] != a.supplier.split()[0]]
            )
        elif kind == "currency":
            b2.currency = "EUR" if a.currency != "EUR" else "GBP"
        left, _ = h.upload(f"cl{i}.pdf", syn.make_pdf([a]))
        right, _ = h.upload(f"cr{i}.xlsx", syn.make_xlsx([b2], "summary"))
        r = h.client.post(
            "/api/v1/comparisons", headers=h.h, json={"left_document_id": left, "right_document_id": right}
        ).json()
        pair = r["pairs"][0]
        verdicts = {it["field"]: it["verdict"] for it in pair["items"]}
        cmp_stats[kind]["pairs"] += 1
        if target:
            cmp_stats[kind]["detected"] += verdicts[target] == "mismatch"
        for fld, v in verdicts.items():
            if fld in FIELDS and fld != target:
                clean_fields += 1
                false_flags += v == "mismatch"
    seeded = sum(v["pairs"] for k, v in cmp_stats.items() if k != "none")
    out["cross_document"] = {
        "by_seeded_discrepancy": cmp_stats,
        "discrepancy_recall": round(sum(v["detected"] for k, v in cmp_stats.items() if k != "none") / seeded, 4),
        "false_mismatch_rate_on_unchanged_fields": round(false_flags / clean_fields, 4),
        "unchanged_fields_compared": clean_fields,
    }

    print("4) OCR ablation: deskew on/off on rotated scans")
    abl: dict[str, Any] = {}
    items = []
    for i in range(n_abl):
        x = inv()
        items.append(
            (
                f"a{i}.pdf",
                syn.make_scanned_pdf(syn.make_pdf([x]), 150, rotate=rng.choice([-4, -3, 3, 4]), blur=0.5, noise=8),
                [x],
            )
        )
    for label, deskew in (("deskew_on", "true"), ("deskew_off", "false")):
        os.environ["OCR_DESKEW"] = deskew
        get_settings.cache_clear()
        reset_runtime()
        # unique bytes per run so the duplicate-file check does not skip processing
        run_items = [(f"{label}{n}", _tweak(data, label), invs) for n, data, invs in items]
        abl[label] = run_condition(h, label, run_items).report()
    os.environ["OCR_DESKEW"] = "true"
    out["ocr_ablation_rotated_scans"] = {
        k: {
            "micro_f1": v["fields_micro_avg"]["f1"],
            "accuracy": v["fields_micro_avg"]["accuracy"],
            "line_item_f1": v["line_items"]["f1"],
        }
        for k, v in abl.items()
    }

    total_docs = sum(c.docs for c in conditions.values())
    finals: dict[str, int] = defaultdict(int)
    for c in conditions.values():
        for k, v in c.statuses.items():
            finals[k] += v
    out["document_outcomes_extraction_set"] = {
        "documents": total_docs,
        "by_final_status": dict(finals),
        "processed_without_failure_rate": round((finals["completed"] + finals["needs_review"]) / total_docs, 4),
    }
    dest = BACKEND.parent / "docs" / "eval_results.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(out, indent=2))
    print(
        json.dumps(
            {
                k: out[k]
                for k in (
                    "validation",
                    "cross_document",
                    "ocr_ablation_rotated_scans",
                    "document_outcomes_extraction_set",
                )
            },
            indent=1,
        )
    )
    for k, v in out["extraction_by_condition"].items():
        print(
            f"{k:34s} micro-F1={v['fields_micro_avg']['f1']:.3f} acc={v['fields_micro_avg']['accuracy']:.3f} lines-F1={(v['line_items']['f1'] if isinstance(v['line_items'], dict) else float('nan')):.3f} fully-correct={v['invoices_fully_correct']}"
        )
    print("written", dest)


def _tweak(pdf: bytes, label: str) -> bytes:
    """Make the bytes unique per run (PDF tolerates trailing comments) so de-duplication does not skip it."""
    return pdf + f"\n%{label}\n".encode()


if __name__ == "__main__":
    main()
