"""End-to-end pipeline tests through the real API, real PostgreSQL and eager Celery."""

from __future__ import annotations

import random
import shutil
from typing import Any

import pytest

from app.devtools import synthetic as syn
from tests.conftest import Uploader, field_values

HAS_TESSERACT = shutil.which("tesseract") is not None
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


def assert_matches(logical: dict[str, Any], truth: dict[str, Any], fields: list[str] = FIELDS) -> None:
    got = field_values(logical)
    for name in fields:
        assert got[name] == truth[name], f"{name}: {got[name]!r} != {truth[name]!r}"
    assert len(logical["line_items"]) == len(truth["line_items"])
    for li, t in zip(logical["line_items"], truth["line_items"], strict=True):
        assert li["description"] == t["description"]
        assert float(li["amount"]) == pytest.approx(float(t["amount"]))


def test_digital_pdf_end_to_end(upload: Uploader, rng: random.Random) -> None:
    inv = syn.random_invoice(rng, 1)
    doc_id = upload.one("invoice.pdf", syn.make_pdf([inv]))
    status = upload.status(doc_id)
    assert status["status"] == "completed", status
    assert status["progress"] == 1.0
    (logical,) = upload.extractions(doc_id)
    assert logical["doc_type"] == "invoice"
    assert logical["validation_status"] == "valid", logical["validation"]
    assert logical["needs_review"] is False
    assert_matches(logical, inv.truth())
    total = next(f for f in logical["fields"] if f["name"] == "total_amount")
    assert total["bbox"] and total["page"] == 1 and total["source"] == "extracted" and total["grounded"]


def test_multi_invoice_bundle_is_split(upload: Uploader, rng: random.Random) -> None:
    invs = [syn.random_invoice(rng, i) for i in range(1, 5)]
    invs[1].items = invs[1].items * 3
    invs[1].items_per_page = 4  # spans several pages
    doc_id = upload.one("bundle.pdf", syn.make_pdf(invs, filler_pages=1))
    assert upload.status(doc_id)["status"] == "completed"
    logicals = [l for l in upload.extractions(doc_id) if l["doc_type"] == "invoice"]
    assert len(logicals) == 4
    for logical, inv in zip(logicals, invs, strict=True):
        assert_matches(logical, inv.truth())
    others = [l for l in upload.extractions(doc_id) if l["doc_type"] == "other"]
    assert len(others) == 1


def test_arithmetic_error_is_flagged_deterministically(upload: Uploader, rng: random.Random) -> None:
    inv = syn.random_invoice(rng, 2)
    inv.total_override = inv.subtotal + inv.tax + 50
    doc_id = upload.one("bad_total.pdf", syn.make_pdf([inv]))
    assert upload.status(doc_id)["status"] == "needs_review"
    (logical,) = upload.extractions(doc_id)
    codes = {v["rule_code"]: v for v in logical["validation"]}
    assert "TOTAL_MISMATCH" in codes
    assert codes["TOTAL_MISMATCH"]["severity"] == "error"
    assert float(codes["TOTAL_MISMATCH"]["expected"]) == pytest.approx(float(inv.subtotal + inv.tax))
    assert logical["needs_review"] is True


@pytest.mark.skipif(not HAS_TESSERACT, reason="tesseract not installed")
def test_scanned_pdf_uses_ocr(upload: Uploader, rng: random.Random) -> None:
    inv = syn.random_invoice(rng, 3)
    scan = syn.make_scanned_pdf(syn.make_pdf([inv]), 150, rotate=1.5, blur=0.6, noise=8)
    doc_id = upload.one("scan.pdf", scan)
    assert upload.status(doc_id)["status"] in ("completed", "needs_review")
    (logical,) = upload.extractions(doc_id)
    assert_matches(logical, inv.truth())
    page = upload.client.get(f"/api/v1/documents/{doc_id}/pages/1", headers=upload.headers).json()
    assert page["method"] == "ocr" and page["ocr_confidence"] > 0.7


@pytest.mark.skipif(not HAS_TESSERACT, reason="tesseract not installed")
@pytest.mark.parametrize("fmt,name", [("PNG", "a.png"), ("JPEG", "a.jpg")])
def test_single_image_documents(upload: Uploader, rng: random.Random, fmt: str, name: str) -> None:
    inv = syn.random_invoice(rng, 4)
    doc_id = upload.one(name, syn.make_image(syn.make_pdf([inv]), fmt, dpi=150))
    assert upload.status(doc_id)["status"] in ("completed", "needs_review")
    (logical,) = upload.extractions(doc_id)
    assert_matches(logical, inv.truth())


@pytest.mark.skipif(not HAS_TESSERACT, reason="tesseract not installed")
def test_multipage_tiff_is_split_into_invoices(upload: Uploader, rng: random.Random) -> None:
    invs = [syn.random_invoice(rng, 5), syn.random_invoice(rng, 6)]
    doc_id = upload.one("batch.tiff", syn.make_tiff(syn.make_pdf(invs), 150))
    assert upload.status(doc_id)["page_count"] == 2
    logicals = [l for l in upload.extractions(doc_id) if l["doc_type"] == "invoice"]
    assert len(logicals) == 2
    for logical, inv in zip(logicals, invs, strict=True):
        assert_matches(logical, inv.truth())


def test_xlsx_summary_and_lines_layouts(upload: Uploader, rng: random.Random) -> None:
    invs = [syn.random_invoice(rng, i) for i in range(1, 4)]
    doc_id = upload.one("register.xlsx", syn.make_xlsx(invs, "summary"))
    logicals = upload.extractions(doc_id)
    assert upload.doc(doc_id)["page_count"] == 2  # two sheets
    assert [l["provider"] for l in logicals] == ["spreadsheet-mapper"] * 3
    for logical, inv in zip(logicals, invs, strict=True):
        assert field_values(logical)["invoice_number"] == inv.invoice_number
        assert field_values(logical)["total_amount"] == format(inv.total, "f")
        cell = next(f for f in logical["fields"] if f["name"] == "total_amount")["bbox"]
        assert cell["sheet"] == "Invoices" and cell["cell"].startswith("Invoices!G")
        # a summary sheet has no line-item columns, so "no line items" must not trigger a review
        assert "LINE_ITEMS_MISSING" not in {v["rule_code"] for v in logical["validation"]}
        assert logical["validation_status"] == "valid" and logical["needs_review"] is False

    inv2 = syn.random_invoice(rng, 9)
    doc2 = upload.one("lines.xlsx", syn.make_xlsx([inv2], "lines", header_row=5))
    (l2,) = upload.extractions(doc2)
    assert len(l2["line_items"]) == len(inv2.items)
    assert l2["validation_status"] in ("valid", "warnings")


def test_csv_with_semicolons_and_latin1(upload: Uploader, rng: random.Random) -> None:
    invs = [syn.random_invoice(rng, 7)]
    invs[0].supplier = "Café Müller GmbH"
    doc_id = upload.one("data.csv", syn.make_csv(invs, ";", "cp1252"))
    (logical,) = upload.extractions(doc_id)
    assert field_values(logical)["supplier_name"] == "Café Müller GmbH"


def test_xls_legacy_format(upload: Uploader) -> None:
    import io

    import xlwt

    wb = xlwt.Workbook()
    ws = wb.add_sheet("Sheet1")
    for c, h in enumerate(["Invoice No", "Date", "Vendor", "Total", "Currency"]):
        ws.write(0, c, h)
    for c, v in enumerate(["OLD-1", "2024-05-01", "Legacy Corp", 99.5, "USD"]):
        ws.write(1, c, v)
    buf = io.BytesIO()
    wb.save(buf)
    doc_id = upload.one("legacy.xls", buf.getvalue())
    (logical,) = upload.extractions(doc_id)
    assert field_values(logical)["invoice_number"] == "OLD-1"
    assert field_values(logical)["total_amount"] == "99.5"


def test_duplicate_file_is_detected(upload: Uploader, rng: random.Random) -> None:
    data = syn.make_pdf([syn.random_invoice(rng, 1)])
    first = upload(("a.pdf", data))[0]
    second = upload(("copy-of-a.pdf", data))[0]
    assert first["status"] == "accepted" and second["status"] == "duplicate"
    assert first["document_id"] == second["document_id"]


def test_duplicate_invoice_in_different_files_is_flagged(upload: Uploader, rng: random.Random) -> None:
    inv = syn.random_invoice(rng, 1)
    d1 = upload.one("one.pdf", syn.make_pdf([inv]))
    d2 = upload.one("two.pdf", syn.make_pdf([inv], filler_pages=1))  # different bytes, same invoice
    for d in (d1, d2):
        (logical,) = [l for l in upload.extractions(d) if l["doc_type"] == "invoice"]
        assert "DUPLICATE_INVOICE" in {v["rule_code"] for v in logical["validation"]}, d
        assert logical["needs_review"] is True


def test_mixed_batch_upload_reports_each_file(upload: Uploader, rng: random.Random) -> None:
    good = syn.make_pdf([syn.random_invoice(rng, 1)])
    results = upload(("good.pdf", good), ("evil.pdf", b"MZ\x90\x00 not a pdf at all"), ("notes.txt", b"hello"))
    assert [r["status"] for r in results] == ["accepted", "rejected", "rejected"]
    assert "does not match" in results[1]["reason"]
    assert "Unsupported" in results[2]["reason"]


def test_all_rejected_returns_422(upload: Uploader) -> None:
    upload(("x.pdf", b"not a pdf"), expect=422)


def test_garbage_pdf_is_rejected_with_reason(upload: Uploader) -> None:
    res = upload(("junk.pdf", b"%PDF-1.4\n" + b"\x00\x01garbage" * 50))[0]
    assert res["status"] == "accepted"  # magic bytes pass; the deep integrity check happens in the worker
    assert upload.status(res["document_id"])["status"] == "rejected"
    assert "corrupted" in upload.doc(res["document_id"])["error_message"].lower()


def test_truncated_pdf_is_repaired_but_always_needs_review(upload: Uploader, rng: random.Random) -> None:
    good = syn.make_pdf([syn.random_invoice(rng, 1), syn.random_invoice(rng, 2)], filler_pages=3)
    doc_id = upload.one("trunc.pdf", good[: len(good) // 2])
    assert upload.status(doc_id)["status"] == "needs_review"
    events = upload.client.get(f"/api/v1/documents/{doc_id}/history", headers=upload.headers).json()
    assert any(e["status"] == "warning" and "repaired" in e["message"] for e in events)


def test_encrypted_pdf_is_rejected(upload: Uploader, rng: random.Random) -> None:
    import pymupdf

    doc = pymupdf.open(stream=syn.make_pdf([syn.random_invoice(rng, 1)]), filetype="pdf")
    data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="secret", owner_pw="secret")
    doc_id = upload.one("locked.pdf", data)
    assert upload.status(doc_id)["status"] == "rejected"
    assert "password" in (upload.doc(doc_id)["error_message"] or "").lower()


def test_history_and_status_endpoints(upload: Uploader, rng: random.Random) -> None:
    doc_id = upload.one("h.pdf", syn.make_pdf([syn.random_invoice(rng, 1)]))
    events = upload.client.get(f"/api/v1/documents/{doc_id}/history", headers=upload.headers).json()
    stages = [e["stage"] for e in events]
    for expected in ("upload", "validation", "analysis", "extraction", "document"):
        assert expected in stages
    assert events[-1]["status"] == "completed"


def test_file_download_and_page_image(upload: Uploader, rng: random.Random) -> None:
    data = syn.make_pdf([syn.random_invoice(rng, 1)])
    doc_id = upload.one("d.pdf", data)
    r = upload.client.get(f"/api/v1/documents/{doc_id}/file", headers=upload.headers)
    assert r.status_code == 200 and r.content == data
    assert r.headers["content-security-policy"].startswith("sandbox")
    img = upload.client.get(f"/api/v1/documents/{doc_id}/pages/1/image", headers=upload.headers)
    assert img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n"
