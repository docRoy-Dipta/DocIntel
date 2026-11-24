"""Effective values: the current extraction with human corrections layered on top.

Extractions are versioned and never overwritten. A correction is a separate row, so reprocessing
cannot silently destroy a reviewer's work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schemas import FIELD_NAMES
from app.core.config import Settings
from app.db.models import Correction, ExtractedField, Extraction, LineItem, LogicalDocument, Page
from app.domain.dates import parse_date
from app.domain.money import currency_mentions, parse_amount
from app.domain.validation import InvoiceData, LineItemData

AMOUNT_FIELDS = {"subtotal", "tax", "total_amount", "tax_rate"}
CORRECTABLE_FIELDS = set(FIELD_NAMES)


@dataclass
class EffectiveField:
    name: str
    value: str | None
    original_value: str | None
    corrected: bool
    field_id: int | None
    confidence: float
    source: str
    grounded: bool
    page: int | None
    bbox: Any
    raw_text: str | None


def current_extraction(session: Session, logical_id: int) -> Extraction | None:
    return session.scalar(
        select(Extraction)
        .where(Extraction.logical_document_id == logical_id, Extraction.is_current.is_(True))
        .order_by(Extraction.version.desc())
    )


def effective_fields(session: Session, logical_id: int) -> dict[str, EffectiveField]:
    out: dict[str, EffectiveField] = {}
    ext = current_extraction(session, logical_id)
    rows = (
        {f.name: f for f in session.scalars(select(ExtractedField).where(ExtractedField.extraction_id == ext.id))}
        if ext
        else {}
    )
    corrections: dict[str, Correction] = {}
    for row in session.scalars(
        select(Correction)
        .where(Correction.logical_document_id == logical_id, Correction.target_type == "field")
        .order_by(Correction.id)
    ):
        corrections[row.field_name] = row  # later corrections win
    for name in FIELD_NAMES:
        f = rows.get(name)
        c = corrections.get(name)
        out[name] = EffectiveField(
            name=name,
            value=(c.new_value if c else (f.value if f else None)),
            original_value=f.value if f else None,
            corrected=c is not None,
            field_id=f.id if f else None,
            confidence=(1.0 if c else (f.confidence if f else 0.0)),
            source=("corrected" if c else (f.source if f else "extracted")),
            grounded=True if c else (f.grounded if f else True),
            page=f.page if f else None,
            bbox=f.bbox if f else None,
            raw_text=f.raw_text if f else None,
        )
    return out


def current_line_items(session: Session, extraction_id: int | None) -> list[LineItem]:
    if extraction_id is None:
        return []
    return list(
        session.scalars(select(LineItem).where(LineItem.extraction_id == extraction_id).order_by(LineItem.position))
    )


def _dec(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return parse_amount(value)


def _date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return parse_date(value).value


def to_invoice_data(
    session: Session,
    logical: LogicalDocument,
    fields: dict[str, EffectiveField],
    settings: Settings,
) -> InvoiceData:
    ext = current_extraction(session, logical.id)
    items = current_line_items(session, ext.id if ext else None)
    page_text = "\n".join(
        session.scalars(
            select(Page.text).where(
                Page.document_id == logical.document_id,
                Page.page_number.between(logical.start_page, logical.end_page),
            )
        )
    )
    uncorrected = {n: f for n, f in fields.items() if not f.corrected}
    date_field = fields["invoice_date"]
    ambiguous = bool(date_field.raw_text and not date_field.corrected and parse_date(date_field.raw_text).ambiguous)
    return InvoiceData(
        invoice_number=fields["invoice_number"].value,
        invoice_date=_date(fields["invoice_date"].value),
        supplier_name=fields["supplier_name"].value,
        customer_name=fields["customer_name"].value,
        subtotal=_dec(fields["subtotal"].value),
        tax=_dec(fields["tax"].value),
        total_amount=_dec(fields["total_amount"].value),
        currency=(fields["currency"].value or None),
        tax_rate=_dec(fields["tax_rate"].value),
        line_items=[LineItemData(i.position, i.description, i.quantity, i.unit_price, i.amount) for i in items],
        inferred_fields={
            n for n, f in uncorrected.items() if f.value is not None and f.source == "inferred" and n != "tax_rate"
        },
        ungrounded_fields={n for n, f in uncorrected.items() if not f.grounded},
        low_confidence_fields={
            n
            for n, f in uncorrected.items()
            if f.value is not None and f.grounded and f.confidence < settings.review_confidence_threshold
        },
        ambiguous_date=ambiguous,
        currency_mentions=currency_mentions(page_text) if logical.source == "rules" else set(),
        expect_line_items=not (logical.source == "spreadsheet" and not (logical.sheet_ref or {}).get("has_line_items")),
    )


def refresh_summary(logical: LogicalDocument, fields: dict[str, EffectiveField]) -> None:
    """Copy effective header values onto the logical document row (for fast filtering/sorting)."""
    logical.invoice_number = fields["invoice_number"].value or None
    logical.supplier_name = fields["supplier_name"].value
    logical.customer_name = fields["customer_name"].value
    logical.invoice_date = _date(fields["invoice_date"].value)
    logical.total_amount = _dec(fields["total_amount"].value)
    logical.currency = fields["currency"].value


def normalize_input(name: str, text: str | None) -> str | None:
    """Validate and normalise a human-entered value. Raises ValueError with a friendly message."""
    if text is None or str(text).strip() == "":
        return None
    s = str(text).strip()
    if name in AMOUNT_FIELDS:
        v = parse_amount(s)
        if v is None:
            raise ValueError(f"'{s}' is not a valid number.")
        return format(v, "f")
    if name == "invoice_date":
        parsed = parse_date(s)
        if parsed.value is None:
            raise ValueError("Use a valid date, preferably YYYY-MM-DD.")
        if parsed.ambiguous:
            raise ValueError("Ambiguous date (day/month order). Please enter it as YYYY-MM-DD.")
        return parsed.value.isoformat()
    if name == "currency":
        if not re.fullmatch(r"[A-Za-z]{3}", s):
            raise ValueError("Currency must be a 3-letter ISO code such as USD.")
        return s.upper()
    if len(s) > 300:
        raise ValueError("Value is too long (max 300 characters).")
    return s
