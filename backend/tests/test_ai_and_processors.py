"""Tests for classification, grounding, the Gemini client (mocked HTTP), files, spreadsheets, OCR, embeddings."""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from datetime import datetime
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.ai.embeddings import HashingEmbedder, chunk_text
from app.ai.extractor import merge_raw
from app.ai.gemini import GeminiExtractor
from app.ai.grounding import is_field_grounded, is_line_grounded
from app.ai.heuristic import HeuristicExtractor
from app.ai.schemas import PageText, RawField, RawInvoice, RawLineItem
from app.ai.scoring import score_extraction
from app.core.config import Settings
from app.core.errors import FileRejectedError, PermanentProcessingError, TransientProcessingError
from app.core.ratelimit import MemoryRateLimiter, RedisRateLimiter
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.devtools import synthetic as syn
from app.processors.classify import classify_page, split_pages
from app.processors.files import detect_kind, validate_integrity
from app.processors.layout import Word, locate, words_to_text
from app.processors.spreadsheet import SheetData, extract_records, read_csv, read_workbook

SETTINGS = Settings(app_env="test", jwt_secret="x" * 40)
INVOICE_TEXT = "Acme Ltd\nINVOICE\nInvoice No: INV-7\nInvoice Date: 2025-03-01\nBill To: Globex\nWidget  2  $5.00  $10.00\nSubtotal  $10.00\nTax (10%)  $1.00\nTotal  $11.00\nCurrency: USD"  # noqa: E501


# ----------------------------------------------------------------------------- classification / splitting


def test_classification() -> None:
    assert classify_page(INVOICE_TEXT).doc_type == "invoice" and classify_page(INVOICE_TEXT).is_start
    receipt = classify_page("RECEIPT\nReceipt No: R-1\nPayment received. Thank you for your payment.")
    assert receipt.doc_type == "receipt" and receipt.is_start
    assert classify_page("Terms and conditions apply to all sales.").doc_type == "other"
    cont = classify_page(
        "Invoice INV-7 (continued)\nWidget 1 5.00 5.00\nSubtotal 15.00\nTotal 16.50\nTax 1.50\nPage 2 of 2"
    )
    assert cont.looks_like_continuation and not cont.is_start


def test_split_pages_groups_continuations_and_separates_documents() -> None:
    cont = "Invoice INV-1 (continued)\nItem  1  5.00  5.00\nSubtotal  15.00\nTax  1.50\nTotal  16.50\nPage 2 of 2"
    pages = [
        (1, INVOICE_TEXT),
        (2, cont),
        (3, INVOICE_TEXT.replace("INV-7", "INV-8")),
        (4, "random legal text"),
        (5, "more legal text"),
    ]
    spans = [(s.doc_type, s.start_page, s.end_page) for s in split_pages(pages)]
    assert spans == [("invoice", 1, 2), ("invoice", 3, 3), ("other", 4, 5)]


# ----------------------------------------------------------------------------- layout


def test_words_to_text_rebuilds_lines_and_columns() -> None:
    words = [
        Word(10, 10, 60, 20, "Total"),
        Word(200, 11, 250, 21, "$5.00"),
        Word(10, 40, 50, 50, "Next"),
        Word(55, 40, 90, 50, "line"),
    ]
    assert words_to_text(words).split("\n") == ["Total  $5.00", "Next line"]
    assert locate(words, "next LINE") == ([10.0, 40.0, 90.0, 50.0], None)
    assert locate(words, "missing") is None


# ----------------------------------------------------------------------------- grounding & scoring


def test_grounding_rules() -> None:
    texts = {1: INVOICE_TEXT}
    assert is_field_grounded("total_amount", RawField(value="11.00", raw_text="Total  $11.00", page=1), texts)
    assert not is_field_grounded("total_amount", RawField(value="12.00", raw_text="Total  $12.00", page=1), texts)
    assert not is_field_grounded(
        "total_amount", RawField(value="99.00", raw_text="Total  $11.00", page=1), texts
    )  # value contradicts quote
    assert is_field_grounded(
        "tax", RawField(value="1.00", raw_text="Tax (10%)  $1.00", page=1), texts
    )  # % is not part of the amount
    assert is_field_grounded(
        "invoice_date",
        RawField(value="2025-03-01", raw_text="Invoice Date: 2025-03-01", page=1),
        texts,
    )
    assert not is_field_grounded(
        "invoice_number", RawField(value="INV-999", raw_text="Invoice No: INV-999", page=1), texts
    )
    assert is_field_grounded("currency", RawField(value="USD", raw_text="$", page=1, source="inferred"), texts)
    assert is_field_grounded("customer_name", RawField(value="Globex"), texts)  # no quote: value must still appear
    assert not is_field_grounded("customer_name", RawField(value="Initech"), texts)
    assert is_line_grounded(
        RawLineItem(description="Widget", amount="10.00", raw_text="Widget  2  $5.00  $10.00", page=1),
        texts,
    )
    assert not is_line_grounded(RawLineItem(description="Ghost", amount="1.00"), texts)


def test_scoring_confidence_signals() -> None:
    pages = [PageText(1, INVOICE_TEXT)]
    raw = HeuristicExtractor().extract(pages)[0]
    scored = score_extraction(raw, pages)
    assert scored.overall_confidence == 0.97 and scored.fields["total_amount"].value == "11.00"
    raw.currency = RawField(value="USD", raw_text="$", page=1, source="inferred")
    assert score_extraction(raw, pages).fields["currency"].confidence <= 0.6  # inferred values are capped
    raw.total_amount = RawField(value="500.00", raw_text="Total $500.00", page=1)
    out = score_extraction(raw, pages)
    assert out.fields["total_amount"].value is None and out.fields["total_amount"].rejected_value == "500.00"
    ocr_pages = [PageText(1, INVOICE_TEXT, [], 0.62, "ocr")]
    assert score_extraction(HeuristicExtractor().extract(ocr_pages)[0], ocr_pages).overall_confidence == pytest.approx(
        0.62, abs=0.01
    )


def test_heuristic_extractor_edge_cases() -> None:
    text = "Receipt\nReceipt No: R-5\nInvoice No: INV-5\nDate: 03/04/2025\nTotal  1.234,56 EUR"
    raw = HeuristicExtractor().extract([PageText(1, text)], "receipt")[0]
    assert raw.invoice_number.value == "INV-5"
    assert (
        raw.invoice_date.value == "2025-04-03" and raw.invoice_date.source == "inferred"
    )  # ambiguous order is admitted
    assert raw.total_amount.value == "1234.56" and raw.currency.value == "EUR"
    empty = HeuristicExtractor().extract([PageText(1, "nothing useful here")])[0]
    assert empty.invoice_number.value is None and empty.total_amount.value is None and empty.line_items == []


def test_merge_of_chunk_results() -> None:
    a = RawInvoice(
        invoice_number=RawField(value="A1"),
        total_amount=RawField(value="1"),
        line_items=[RawLineItem(description="x", amount="1", page=1)],
    )
    b = RawInvoice(
        total_amount=RawField(value="99"),
        tax=RawField(value="9"),
        line_items=[
            RawLineItem(description="x", amount="1", page=1),
            RawLineItem(description="y", amount="2", page=2),
        ],
    )
    merged = merge_raw([a, b])
    assert merged.invoice_number.value == "A1" and merged.total_amount.value == "99" and merged.tax.value == "9"
    assert [i.description for i in merged.line_items] == ["x", "y"]


# ----------------------------------------------------------------------------- Gemini client (HTTP mocked)


def gemini(handler: Any, **kw: Any) -> GeminiExtractor:
    return GeminiExtractor("key-123", "gemini-test", transport=httpx.MockTransport(handler), **kw)


GOOD = {
    f: {"value": None, "raw_text": None, "page": None, "source": "extracted"}
    for f in [
        "invoice_number",
        "invoice_date",
        "supplier_name",
        "customer_name",
        "subtotal",
        "tax",
        "total_amount",
        "currency",
        "tax_rate",
    ]
}


def test_gemini_request_shape_and_parsing() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["key"], seen["body"] = (
            str(req.url),
            req.headers["x-goog-api-key"],
            json.loads(req.content),
        )
        payload = {
            **GOOD,
            "invoice_number": {
                "value": "INV-7",
                "raw_text": "Invoice No: INV-7",
                "page": 1,
                "source": "extracted",
            },
            "line_items": [],
        }
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}],
                "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30},
            },
        )

    raw, usage = gemini(handler).extract([PageText(1, INVOICE_TEXT)])
    assert raw.invoice_number.value == "INV-7" and usage == {
        "prompt_tokens": 120,
        "output_tokens": 30,
    }
    assert seen["url"].endswith("/models/gemini-test:generateContent") and seen["key"] == "key-123"
    cfg = seen["body"]["generationConfig"]
    assert (
        cfg["temperature"] == 0
        and cfg["responseMimeType"] == "application/json"
        and cfg["responseSchema"]["type"] == "OBJECT"
    )
    assert "Invoice No: INV-7" in seen["body"]["contents"][0]["parts"][0]["text"]
    assert "key-123" not in seen["url"]  # the API key travels in a header, never in the URL


@pytest.mark.parametrize(
    "status,exc",
    [
        (429, TransientProcessingError),
        (503, TransientProcessingError),
        (400, PermanentProcessingError),
        (403, PermanentProcessingError),
    ],
)
def test_gemini_error_classification(status: int, exc: type[Exception]) -> None:
    with pytest.raises(exc):
        gemini(lambda r: httpx.Response(status, json={"error": "x"})).extract([PageText(1, "t")])


def test_gemini_bad_output_and_network_errors_are_transient() -> None:
    bad = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})
    with pytest.raises(TransientProcessingError):
        gemini(lambda r: bad).extract([PageText(1, "t")])

    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=req)

    with pytest.raises(TransientProcessingError):
        gemini(boom).extract([PageText(1, "t")])


def test_gemini_respects_rate_limit() -> None:
    sleeps: list[float] = []
    allowed = iter([False, False, True])
    ok = httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": json.dumps({**GOOD, "line_items": []})}]}}]},
    )
    gemini(lambda r: ok, rate_limit=lambda: next(allowed), sleep=sleeps.append).extract([PageText(1, "t")])
    assert sleeps == [1.0, 1.0]


# ----------------------------------------------------------------------------- files


def write(tmp: Path, name: str, data: bytes) -> Path:
    p = tmp / "upload.part"
    p.write_bytes(data)
    return p


def test_detect_kind_by_content(tmp_path: Path, rng: Any) -> None:
    pdf = syn.make_pdf([syn.random_invoice(rng, 1)])
    assert detect_kind(write(tmp_path, "a", pdf), "a.PDF", SETTINGS).kind == "pdf"
    assert detect_kind(write(tmp_path, "a", syn.make_image(pdf, "PNG")), "a.png", SETTINGS).kind == "image"
    assert detect_kind(write(tmp_path, "a", syn.make_image(pdf, "JPEG")), "a.jpeg", SETTINGS).kind == "image"
    assert detect_kind(write(tmp_path, "a", syn.make_tiff(pdf)), "a.tif", SETTINGS).kind == "image"
    assert (
        detect_kind(write(tmp_path, "a", syn.make_xlsx([syn.random_invoice(rng, 1)])), "a.xlsx", SETTINGS).kind
        == "xlsx"
    )
    assert detect_kind(write(tmp_path, "a", b"a,b\n1,2\n"), "a.csv", SETTINGS).kind == "csv"
    with pytest.raises(FileRejectedError):
        detect_kind(write(tmp_path, "a", pdf), "a.png", SETTINGS)
    with pytest.raises(FileRejectedError):
        detect_kind(write(tmp_path, "a", pdf), "a.exe", SETTINGS)
    with pytest.raises(FileRejectedError):
        detect_kind(write(tmp_path, "a", pdf), "noextension", SETTINGS)


def test_integrity_checks(tmp_path: Path, rng: Any) -> None:
    pdf = syn.make_pdf([syn.random_invoice(rng, i) for i in range(3)])
    assert validate_integrity(write(tmp_path, "a", pdf), "pdf", SETTINGS).page_count == 3
    with pytest.raises(FileRejectedError, match="limit"):
        validate_integrity(
            write(tmp_path, "a", pdf),
            "pdf",
            Settings(app_env="test", jwt_secret="x" * 40, max_pages_per_document=2),
        )
    with pytest.raises(FileRejectedError):
        validate_integrity(write(tmp_path, "a", syn.make_image(pdf, "PNG")[:200]), "image", SETTINGS)
    assert validate_integrity(write(tmp_path, "a", syn.make_tiff(pdf)), "image", SETTINGS).page_count == 3


# ----------------------------------------------------------------------------- spreadsheets


def test_header_detection_with_offset_decorated_headers_and_noise() -> None:
    sheet = SheetData(
        "S",
        [
            ["Quarterly report"],
            [None],
            ["Notes: draft"],
            [
                "Invoice Number",
                "Invoice Date (DD/MM/YYYY)",
                "Supplier Name",
                "Grand Total",
                "Currency",
            ],
            ["X-1", "25/12/2024", "Acme", "1,000.50", "USD"],
            [None] * 5,
            ["TOTAL", None, None, 1000.5, None],
        ],
    )
    (rec,) = extract_records(sheet)
    assert rec.fields["invoice_number"].ref == "S!A5" and rec.fields["total_amount"].value == D("1000.50")
    assert rec.fields["invoice_date"].value.isoformat() == "2024-12-25"
    assert extract_records(SheetData("S", [["foo", "bar"], [1, 2]])) == []


def test_spreadsheet_dates_and_numbers_from_native_cells() -> None:
    sheet = SheetData("S", [["Invoice", "Date", "Vendor", "Amount"], ["A1", datetime(2025, 5, 4), "V", 0.1 + 0.2]])
    (rec,) = extract_records(sheet)
    assert rec.fields["total_amount"].value == D("0.30000000000000004") or rec.fields["total_amount"].value == D("0.3")
    assert rec.fields["invoice_date"].value.isoformat() == "2025-05-04"


def test_csv_encodings_and_delimiters(tmp_path: Path) -> None:
    for enc, delim in [("utf-8", ","), ("utf-8-sig", ";"), ("cp1252", "\t"), ("utf-16", ",")]:
        p = tmp_path / "x.csv"
        p.write_bytes(f"Invoice No{delim}Vendor{delim}Total\nA-1{delim}Müller & Söhne{delim}5.00\n".encode(enc))
        sheet = read_csv(p, SETTINGS)
        assert sheet.rows[1][1] == "Müller & Söhne", enc


def test_formula_without_cached_value_is_reported(tmp_path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Invoice No", "Vendor", "Total"])
    ws.append(["A-1", "V", "=10+5"])  # openpyxl does not compute formulas: no cached value
    p = tmp_path / "f.xlsx"
    wb.save(p)
    (sheet,) = read_workbook(p, "xlsx", SETTINGS)
    assert any("no cached value" in w for w in sheet.warnings)


def test_xlsx_row_limit_is_enforced(tmp_path: Path) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    for i in range(50):
        ws.append([f"A-{i}", "V", i])
    p = tmp_path / "big.xlsx"
    wb.save(p)
    (sheet,) = read_workbook(p, "xlsx", Settings(app_env="test", jwt_secret="x" * 40, max_sheet_rows=10))
    assert len(sheet.rows) == 10 and any("truncated" in w for w in sheet.warnings)


# ----------------------------------------------------------------------------- OCR


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
@pytest.mark.parametrize("kw", [{}, {"rotate": 3.0}, {"rotate": -2.5, "blur": 0.7, "noise": 10}, {"jpeg_quality": 40}])
def test_ocr_reads_key_tokens_from_degraded_scans(kw: dict[str, Any], tmp_path: Path, rng: Any) -> None:
    from app.processors.pdfpages import ocr_pdf_page

    inv = syn.random_invoice(rng, 1)
    p = tmp_path / "s.pdf"
    p.write_bytes(syn.make_scanned_pdf(syn.make_pdf([inv]), 150, **kw))
    result = ocr_pdf_page(p, 1, SETTINGS)
    squashed = result.text.replace(" ", "")
    assert inv.invoice_number in squashed and f"{inv.total:,.2f}" in squashed
    assert result.ocr_confidence and result.ocr_confidence > 0.7 and result.words


def test_ocr_engine_missing_is_a_permanent_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rng: Any) -> None:
    import pytesseract

    from app.processors.pdfpages import ocr_pdf_page

    def missing(*a: Any, **k: Any) -> Any:
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_data", missing)
    p = tmp_path / "s.pdf"
    p.write_bytes(syn.make_scanned_pdf(syn.make_pdf([syn.random_invoice(rng, 1)]), 100))
    with pytest.raises(PermanentProcessingError, match="not installed"):
        ocr_pdf_page(p, 1, SETTINGS)


# ----------------------------------------------------------------------------- embeddings, security primitives


def test_hashing_embedder_properties() -> None:
    e = HashingEmbedder(384)
    a, b, c = e.embed(["catering banquet service", "banquet catering services for events", "copper pipe fittings"])
    dot = lambda x, y: sum(i * j for i, j in zip(x, y, strict=True))  # noqa: E731
    assert len(a) == 384 and dot(a, a) == pytest.approx(1.0)
    assert dot(a, b) > dot(a, c) and e.embed(["x"]) == e.embed(["x"])  # deterministic
    assert chunk_text("a" * 3200, 1500, 150)[1].startswith("a") and chunk_text("  ") == []


def test_password_hashing_and_tokens() -> None:
    h = hash_password("a-long-password")
    assert h.startswith("scrypt$") and verify_password("a-long-password", h) and not verify_password("other", h)
    assert hash_password("a-long-password") != h  # unique salt
    assert not verify_password("x", "garbage") and not verify_password("x", "bcrypt$1$2$3$4$5")
    tok = create_access_token(subject="7", role="admin", secret="s" * 40, algorithm="HS256", minutes=5)
    assert decode_access_token(tok, secret="s" * 40, algorithm="HS256")["sub"] == "7"


def test_rate_limiters() -> None:
    lim = MemoryRateLimiter()
    assert [lim.hit("k", 3) for _ in range(5)] == [True, True, True, False, False]
    assert lim.hit("other", 3)
    import fakeredis

    rl = RedisRateLimiter(fakeredis.FakeRedis())
    assert [rl.hit("k", 2) for _ in range(4)] == [True, True, False, False]


def test_zip_utilities_are_not_trusting_member_paths(tmp_path: Path) -> None:
    from app.processors.files import check_zip_safety

    p = tmp_path / "evil.xlsx"
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("../../evil.txt", "x")
    with pytest.raises(FileRejectedError, match="unsafe"):
        check_zip_safety(p, SETTINGS)
    _ = io


@pytest.mark.parametrize("glyph", ["$", "€", "£", "·", "¤", "৳", ""])
def test_line_items_tolerate_unknown_currency_glyphs(glyph: str) -> None:
    text = f"Description  Qty  Unit Price  Amount\nItem 0  9  {glyph}356.96  {glyph}3,212.64\nSubtotal  {glyph}3,212.64"
    raw = HeuristicExtractor().extract([PageText(1, text)])[0]
    assert len(raw.line_items) == 1
    item = raw.line_items[0]
    assert (item.description, item.quantity, item.unit_price, item.amount) == ("Item 0", "9", "356.96", "3212.64")
    assert raw.subtotal.value == "3212.64"
