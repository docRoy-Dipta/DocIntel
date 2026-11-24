"""Deterministic financial validation. No database, no AI: only arithmetic and rules.

Every rule has a stable code (e.g. TOTAL_MISMATCH) so it can be tested and shown in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.domain.money import (
    ISO_CURRENCIES,
    amounts_equal,
    currencies_consistent,
)

ERROR, WARNING, INFO = "error", "warning", "info"

REQUIRED_ERROR_FIELDS = (
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "total_amount",
    "currency",
)
REQUIRED_WARNING_FIELDS = ("customer_name", "subtotal", "tax")


@dataclass(frozen=True)
class LineItemData:
    position: int
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None


@dataclass
class InvoiceData:
    """Effective (corrected where applicable) values of one invoice."""

    invoice_number: str | None = None
    invoice_date: date | None = None
    supplier_name: str | None = None
    customer_name: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total_amount: Decimal | None = None
    currency: str | None = None
    tax_rate: Decimal | None = None  # percent, only if the document states one
    line_items: list[LineItemData] = field(default_factory=list)
    # Review signals coming from the extraction step:
    inferred_fields: set[str] = field(default_factory=set)
    ungrounded_fields: set[str] = field(default_factory=set)
    low_confidence_fields: set[str] = field(default_factory=set)
    ambiguous_date: bool = False
    currency_mentions: set[str] = field(default_factory=set)
    expect_line_items: bool = True  # False for summary-level spreadsheets that have no line-item columns


@dataclass(frozen=True)
class Issue:
    code: str
    severity: str
    message: str
    field: str | None = None
    expected: str | None = None
    actual: str | None = None


@dataclass(frozen=True)
class ValidationReport:
    issues: list[Issue]

    @property
    def status(self) -> str:
        if any(i.severity == ERROR for i in self.issues):
            return "errors"
        if any(i.severity == WARNING for i in self.issues):
            return "warnings"
        return "valid"

    @property
    def needs_review(self) -> bool:
        return self.status != "valid"


def _fmt(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def validate_invoice(
    data: InvoiceData,
    *,
    tolerance: Decimal = Decimal("0.01"),
    today: date | None = None,
) -> ValidationReport:
    today = today or date.today()
    issues: list[Issue] = []

    def add(code: str, severity: str, message: str, **kw: object) -> None:
        issues.append(Issue(code, severity, message, **kw))  # type: ignore[arg-type]

    # --- required / missing fields -------------------------------------------------------
    values = data.__dict__
    for name in REQUIRED_ERROR_FIELDS:
        if values.get(name) in (None, ""):
            add("REQUIRED_FIELD_MISSING", ERROR, f"Required field '{name}' is missing.", field=name)
    for name in REQUIRED_WARNING_FIELDS:
        if values.get(name) in (None, ""):
            add("FIELD_MISSING", WARNING, f"Field '{name}' is missing.", field=name)
    if not data.line_items and data.expect_line_items:
        add("LINE_ITEMS_MISSING", WARNING, "No line items were found.", field="line_items")

    # --- numeric sanity ------------------------------------------------------------------
    for name in ("subtotal", "tax", "total_amount"):
        v = values.get(name)
        if v is not None and v < 0:
            add(
                "NEGATIVE_AMOUNT",
                WARNING,
                f"'{name}' is negative (credit note?).",
                field=name,
                actual=_fmt(v),
            )
    if data.tax is not None and data.subtotal is not None and data.subtotal > 0 and data.tax > data.subtotal:
        add(
            "TAX_EXCEEDS_SUBTOTAL",
            WARNING,
            "Tax is larger than the subtotal.",
            field="tax",
            expected=f"<= {_fmt(data.subtotal)}",
            actual=_fmt(data.tax),
        )

    # --- line items ----------------------------------------------------------------------
    for item in data.line_items:
        if item.quantity is not None and item.unit_price is not None and item.amount is not None:
            expected = item.quantity * item.unit_price
            if not amounts_equal(expected, item.amount, tolerance):
                add(
                    "LINE_AMOUNT_MISMATCH",
                    ERROR,
                    f"Line {item.position}: quantity x unit price does not equal the line amount.",
                    field="line_items",
                    expected=_fmt(expected),
                    actual=_fmt(item.amount),
                )
        elif item.amount is None:
            add(
                "LINE_AMOUNT_MISSING",
                WARNING,
                f"Line {item.position} has no amount.",
                field="line_items",
            )

    line_amounts = [i.amount for i in data.line_items if i.amount is not None]
    lines_sum = sum(line_amounts, Decimal(0)) if line_amounts else None

    if lines_sum is not None and data.subtotal is not None and not amounts_equal(lines_sum, data.subtotal, tolerance):
        add(
            "SUBTOTAL_MISMATCH",
            ERROR,
            "The sum of line amounts does not equal the subtotal.",
            field="subtotal",
            expected=_fmt(lines_sum),
            actual=_fmt(data.subtotal),
        )

    # --- tax and total ---------------------------------------------------------------------
    base = data.subtotal if data.subtotal is not None else lines_sum
    if base is not None and data.total_amount is not None:
        expected_total = base + (data.tax or Decimal(0))
        if not amounts_equal(expected_total, data.total_amount, tolerance):
            if data.tax is None and data.total_amount > base:
                # The tax may simply be missing from this document: cannot be verified, not provably wrong.
                add(
                    "TOTAL_UNVERIFIED_TAX_MISSING",
                    WARNING,
                    "The total is higher than the subtotal/lines and no tax was found, so it cannot be verified.",
                    field="total_amount",
                    expected=_fmt(base),
                    actual=_fmt(data.total_amount),
                )
            else:
                add(
                    "TOTAL_MISMATCH",
                    ERROR,
                    "Subtotal + tax does not equal the total.",
                    field="total_amount",
                    expected=_fmt(expected_total),
                    actual=_fmt(data.total_amount),
                )
    if data.tax_rate is not None and data.tax is not None and base is not None:
        expected_tax = base * data.tax_rate / Decimal(100)
        if not amounts_equal(expected_tax, data.tax, max(tolerance, Decimal("0.02"))):
            add(
                "TAX_RATE_MISMATCH",
                ERROR,
                f"Tax does not match the stated rate of {data.tax_rate}%.",
                field="tax",
                expected=_fmt(expected_tax),
                actual=_fmt(data.tax),
            )

    # --- currency ----------------------------------------------------------------------------
    if data.currency and data.currency.upper() not in ISO_CURRENCIES:
        add(
            "CURRENCY_UNKNOWN",
            WARNING,
            f"'{data.currency}' is not a recognised ISO currency code.",
            field="currency",
            actual=data.currency,
        )
    if data.currency_mentions and not currencies_consistent(data.currency_mentions):
        add(
            "CURRENCY_INCONSISTENT",
            ERROR,
            "More than one currency appears in this document.",
            field="currency",
            actual=", ".join(sorted(data.currency_mentions)),
        )

    # --- dates -------------------------------------------------------------------------------
    if data.invoice_date is not None:
        if data.invoice_date > today + timedelta(days=30):
            add(
                "DATE_IN_FUTURE",
                WARNING,
                "Invoice date is more than 30 days in the future.",
                field="invoice_date",
                actual=data.invoice_date.isoformat(),
            )
        if data.invoice_date.year < 1990:
            add(
                "DATE_IMPLAUSIBLE",
                WARNING,
                "Invoice date is implausibly old.",
                field="invoice_date",
                actual=data.invoice_date.isoformat(),
            )
    if data.ambiguous_date:
        add(
            "DATE_AMBIGUOUS",
            WARNING,
            "The date could be read as day/month or month/day.",
            field="invoice_date",
        )

    # --- review signals ----------------------------------------------------------------------
    for name in sorted(data.inferred_fields):
        add(
            "FIELD_INFERRED",
            WARNING,
            f"'{name}' was inferred, not read from the document.",
            field=name,
        )
    for name in sorted(data.ungrounded_fields):
        add(
            "FIELD_UNGROUNDED",
            WARNING,
            f"'{name}' could not be found in the source text.",
            field=name,
        )
    for name in sorted(data.low_confidence_fields):
        add("FIELD_LOW_CONFIDENCE", WARNING, f"'{name}' was read with low confidence.", field=name)

    return ValidationReport(issues)
