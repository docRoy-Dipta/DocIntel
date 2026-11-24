"""Synthetic invoice generator with known ground truth.

Used for tests and for the evaluation script. Synthetic data is EASIER than real-world documents,
so results measured on it are optimistic; the evaluation report says so.
"""

from __future__ import annotations

import io
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import numpy as np
import pymupdf
from PIL import Image, ImageFilter

SUPPLIERS = [
    "Acme Widgets Ltd",
    "Northwind Traders Inc",
    "Blue Harbor Logistics",
    "Sunrise Textiles LLC",
    "Orion Office Supplies",
    "Greenfield Foods Co",
    "Delta Engineering Ltd",
    "Summit Software Corp",
    "Lakeside Printing",
    "Pioneer Hardware Ltd",
    "Crescent Electronics",
    "Harvest Fresh Produce",
]
CUSTOMERS = [
    "Globex Corporation",
    "Initech Solutions",
    "Umbrella Retail Group",
    "Stark Manufacturing",
    "Wayne Enterprises",
    "Hooli Systems",
    "Vandelay Industries",
    "Soylent Foods",
    "Cyberdyne Labs",
]
ITEMS = [
    "Widget A",
    "Gadget B",
    "Consulting services",
    "Office chair",
    "Printer toner",
    "Network cable",
    "Software license",
    "Cleaning service",
    "Steel bracket",
    "Packaging boxes",
    "Maintenance fee",
    "Laptop stand",
    "Safety gloves",
    "Paint (5L)",
    "Training session",
]
SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "BDT": "৳"}
DATE_FORMATS = ["%d %B %Y", "%Y-%m-%d", "%B %d, %Y", "%d %b %Y"]


def _q(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class SyntheticInvoice:
    invoice_number: str
    invoice_date: date
    supplier: str
    customer: str
    currency: str = "USD"
    items: list[tuple[str, Decimal, Decimal]] = field(default_factory=list)  # (description, qty, unit price)
    tax_rate: Decimal = Decimal("10")
    date_format: str = "%d %B %Y"
    show_currency_line: bool = True
    total_override: Decimal | None = None  # inject: printed total is wrong
    subtotal_override: Decimal | None = None  # inject: printed subtotal differs from the sum of the lines
    tax_override: Decimal | None = None  # inject: printed tax does not match the stated rate
    line_amount_overrides: dict[int, Decimal] = field(default_factory=dict)  # inject: wrong line amount
    items_per_page: int = 12

    @property
    def lines(self) -> list[tuple[str, Decimal, Decimal, Decimal]]:
        return [(d, q, u, self.line_amount_overrides.get(i, _q(q * u))) for i, (d, q, u) in enumerate(self.items)]

    @property
    def subtotal(self) -> Decimal:
        if self.subtotal_override is not None:
            return self.subtotal_override
        return sum((a for _, _, _, a in self.lines), Decimal(0))

    @property
    def tax(self) -> Decimal:
        return self.tax_override if self.tax_override is not None else _q(self.subtotal * self.tax_rate / 100)

    @property
    def total(self) -> Decimal:
        return self.total_override if self.total_override is not None else self.subtotal + self.tax

    @property
    def expected_error_codes(self) -> set[str]:
        """The validation rules that SHOULD fire for the injected errors (empty for a clean invoice)."""
        codes: set[str] = set()
        if self.total_override is not None and self.total_override != self.subtotal + self.tax:
            codes.add("TOTAL_MISMATCH")
        if self.subtotal_override is not None and self.subtotal_override != sum(
            (a for _, _, _, a in self.lines), Decimal(0)
        ):
            codes.add("SUBTOTAL_MISMATCH")
        if self.tax_override is not None and self.tax_override != _q(self.subtotal * self.tax_rate / 100):
            codes.add("TAX_RATE_MISMATCH")
        if self.line_amount_overrides:
            codes.add("LINE_AMOUNT_MISMATCH")
        return codes

    def truth(self) -> dict[str, Any]:
        return {
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date.isoformat(),
            "supplier_name": self.supplier,
            "customer_name": self.customer,
            "subtotal": format(self.subtotal, "f"),
            "tax": format(self.tax, "f"),
            "total_amount": format(self.total, "f"),
            "currency": self.currency,
            "line_items": [
                {
                    "description": d,
                    "quantity": format(q.normalize(), "f"),
                    "unit_price": format(u, "f"),
                    "amount": format(a, "f"),
                }
                for d, q, u, a in self.lines
            ],
        }


def random_invoice(rng: random.Random, index: int = 0, *, supplier: str | None = None) -> SyntheticInvoice:
    n_items = rng.randint(2, 6)
    items = [
        (rng.choice(ITEMS), Decimal(rng.randint(1, 9)), _q(Decimal(rng.randint(300, 40000)) / 100))
        for _ in range(n_items)
    ]
    return SyntheticInvoice(
        invoice_number=f"INV-{rng.randint(2000, 9999)}-{index:03d}",
        invoice_date=date(2025, 1, 1) + timedelta(days=rng.randint(0, 330)),
        supplier=supplier or rng.choice(SUPPLIERS),
        customer=rng.choice(CUSTOMERS),
        currency=rng.choice(["USD", "USD", "EUR", "GBP"]),
        items=items,
        tax_rate=rng.choice([Decimal("5"), Decimal("10"), Decimal("15")]),
        date_format=rng.choice(DATE_FORMATS),
    )


# ------------------------------------------------------------------------------ PDF rendering


def _money(v: Decimal, currency: str) -> str:
    return f"{SYMBOLS.get(currency, '')}{v:,.2f}"


def render_invoice(doc: pymupdf.Document, inv: SyntheticInvoice) -> int:
    """Append the invoice's pages to `doc`. Returns the number of pages added."""
    lines = inv.lines
    chunks = [lines[i : i + inv.items_per_page] for i in range(0, len(lines), inv.items_per_page)] or [[]]
    for page_idx, chunk in enumerate(chunks):
        page = doc.new_page(width=595, height=842)
        text = lambda x, y, s, size=11, _p=page: _p.insert_text((x, y), s, fontsize=size, fontname="helv")  # noqa: E731
        if page_idx == 0:
            text(50, 60, inv.supplier, 16)
            text(50, 78, "12 Market Street, Springfield", 9)
            text(50, 120, "INVOICE", 22)
            text(50, 150, f"Invoice No: {inv.invoice_number}")
            text(50, 168, f"Invoice Date: {inv.invoice_date.strftime(inv.date_format)}")
            text(
                50,
                186,
                f"Due Date: {(inv.invoice_date + timedelta(days=30)).strftime(inv.date_format)}",
            )
            text(50, 214, f"Bill To: {inv.customer}")
            y = 260
        else:
            text(50, 60, f"Invoice {inv.invoice_number} (continued)", 10)
            y = 100
        text(50, y, "Description", 10)
        text(330, y, "Qty", 10)
        text(390, y, "Unit Price", 10)
        text(480, y, "Amount", 10)
        y += 20
        for desc, qty, unit, amount in chunk:
            text(50, y, desc)
            text(330, y, format(qty.normalize(), "f"))
            text(390, y, _money(unit, inv.currency))
            text(480, y, _money(amount, inv.currency))
            y += 20
        if page_idx == len(chunks) - 1:
            y += 20
            text(390, y, "Subtotal")
            text(480, y, _money(inv.subtotal, inv.currency))
            text(390, y + 20, f"Tax ({inv.tax_rate.normalize():f}%)")
            text(480, y + 20, _money(inv.tax, inv.currency))
            text(390, y + 40, "Total", 12)
            text(480, y + 40, _money(inv.total, inv.currency), 12)
            if inv.show_currency_line:
                text(50, y + 70, f"Currency: {inv.currency}")
        if len(chunks) > 1:
            text(480, 810, f"Page {page_idx + 1} of {len(chunks)}", 9)
    return len(chunks)


def make_pdf(invoices: list[SyntheticInvoice], filler_pages: int = 0) -> bytes:
    doc = pymupdf.open()
    for inv in invoices:
        render_invoice(doc, inv)
    for i in range(filler_pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text(
            (50, 100),
            f"Terms and conditions, section {i + 1}. Payment is due within thirty days.",
            fontsize=11,
            fontname="helv",
        )
    return bytes(doc.tobytes())


def make_receipt_pdf(inv: SyntheticInvoice, receipt_number: str = "RCT-1") -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    t = lambda x, y, s, size=11: page.insert_text((x, y), s, fontsize=size, fontname="helv")  # noqa: E731
    t(50, 60, inv.supplier, 16)
    t(50, 110, "RECEIPT", 22)
    t(50, 140, f"Receipt No: {receipt_number}")
    t(50, 158, f"Invoice No: {inv.invoice_number}")
    t(50, 176, f"Date: {inv.invoice_date.strftime(inv.date_format)}")
    t(50, 204, f"Bill To: {inv.customer}")
    t(390, 260, "Total")
    t(480, 260, _money(inv.total, inv.currency))
    t(50, 300, "Payment received. Thank you for your payment.")
    t(50, 320, f"Currency: {inv.currency}")
    return bytes(doc.tobytes())


# ------------------------------------------------------------------------------ scan simulation


def degrade(
    img: Image.Image,
    *,
    rotate: float = 0.0,
    blur: float = 0.0,
    noise: float = 0.0,
    seed: int = 0,
    jpeg_quality: int | None = None,
) -> Image.Image:
    out = img.convert("L")
    if rotate:
        out = out.rotate(rotate, resample=Image.Resampling.BICUBIC, fillcolor=255)
    if blur:
        out = out.filter(ImageFilter.GaussianBlur(blur))
    if noise:
        rng = np.random.default_rng(seed)
        arr = np.asarray(out, dtype=np.float32) + rng.normal(0, noise, size=(out.height, out.width))
        out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    if jpeg_quality:
        buf = io.BytesIO()
        out.save(buf, format="JPEG", quality=jpeg_quality)
        out = Image.open(io.BytesIO(buf.getvalue())).convert("L")
    return out.convert("RGB")


def render_pages(pdf_bytes: bytes, dpi: int = 150) -> list[Image.Image]:
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    images = []
    for i in range(doc.page_count):
        pix = doc.load_page(i).get_pixmap(dpi=dpi, alpha=False)
        images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return images


def make_scanned_pdf(pdf_bytes: bytes, dpi: int = 150, **degrade_kw: Any) -> bytes:
    """An image-only PDF (no text layer), optionally degraded like a poor scan."""
    out = pymupdf.open()
    for i, img in enumerate(render_pages(pdf_bytes, dpi)):
        img = degrade(img, seed=i, **degrade_kw)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        page = out.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=buf.getvalue())
    return bytes(out.tobytes())


def make_image(pdf_bytes: bytes, fmt: str = "PNG", page: int = 0, dpi: int = 150, **degrade_kw: Any) -> bytes:
    img = degrade(render_pages(pdf_bytes, dpi)[page], **degrade_kw)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def make_tiff(pdf_bytes: bytes, dpi: int = 150, **degrade_kw: Any) -> bytes:
    frames = [degrade(i, seed=n, **degrade_kw) for n, i in enumerate(render_pages(pdf_bytes, dpi))]
    buf = io.BytesIO()
    frames[0].save(buf, format="TIFF", save_all=True, append_images=frames[1:])
    return buf.getvalue()


# ------------------------------------------------------------------------------ spreadsheets


def make_xlsx(
    invoices: list[SyntheticInvoice],
    layout: str = "summary",
    header_row: int = 3,
    sheet_name: str = "Invoices",
    extra_sheet: bool = True,
) -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = sheet_name
    ws.cell(row=1, column=1, value="Invoice register (synthetic)")
    r0 = header_row
    if layout == "summary":
        headers = ["Invoice No", "Date", "Vendor", "Customer", "Net", "VAT", "Total", "Currency"]
        for c, h in enumerate(headers, 1):
            ws.cell(row=r0, column=c, value=h)
        for i, inv in enumerate(invoices, 1):
            row = [
                inv.invoice_number,
                inv.invoice_date,
                inv.supplier,
                inv.customer,
                float(inv.subtotal),
                float(inv.tax),
                float(inv.total),
                inv.currency,
            ]
            for c, v in enumerate(row, 1):
                ws.cell(row=r0 + i, column=c, value=v)
        ws.cell(row=r0 + len(invoices) + 1, column=1, value="Total")
    else:
        headers = [
            "Invoice Number",
            "Invoice Date",
            "Supplier",
            "Customer",
            "Description",
            "Qty",
            "Unit Price",
            "Amount",
            "Total",
            "Currency",
        ]
        for c, h in enumerate(headers, 1):
            ws.cell(row=r0, column=c, value=h)
        row_no = r0 + 1
        for inv in invoices:
            for j, (d, q, u, a) in enumerate(inv.lines):
                vals = [
                    inv.invoice_number,
                    inv.invoice_date if j == 0 else None,
                    inv.supplier if j == 0 else None,
                    inv.customer if j == 0 else None,
                    d,
                    float(q),
                    float(u),
                    float(a),
                    float(inv.total) if j == 0 else None,
                    inv.currency if j == 0 else None,
                ]
                for c, v in enumerate(vals, 1):
                    ws.cell(row=row_no, column=c, value=v)
                row_no += 1
    if extra_sheet:
        notes = wb.create_sheet("Notes")
        notes.cell(row=1, column=1, value="Prepared by finance team. Nothing to extract here.")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_csv(invoices: list[SyntheticInvoice], delimiter: str = ",", encoding: str = "utf-8") -> bytes:
    lines = [
        delimiter.join(
            [
                "Invoice Number",
                "Invoice Date",
                "Supplier",
                "Customer",
                "Subtotal",
                "Tax",
                "Total",
                "Currency",
            ]
        )
    ]
    for inv in invoices:
        lines.append(
            delimiter.join(
                [
                    inv.invoice_number,
                    inv.invoice_date.isoformat(),
                    inv.supplier,
                    inv.customer,
                    format(inv.subtotal, "f"),
                    format(inv.tax, "f"),
                    format(inv.total, "f"),
                    inv.currency,
                ]
            )
        )
    return ("\n".join(lines) + "\n").encode(encoding)
