"""Data shapes shared by all extractors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.processors.layout import Word

FIELD_NAMES = (
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total_amount",
    "currency",
    "tax_rate",
)
REQUIRED_FIELDS = ("invoice_number", "invoice_date", "supplier_name", "total_amount", "currency")
IDENTITY_FIELDS = ("invoice_number", "invoice_date", "supplier_name", "customer_name", "currency")
TOTAL_FIELDS = ("subtotal", "tax", "total_amount", "tax_rate")


class RawField(BaseModel):
    """One field as returned by an extractor, before grounding and scoring.

    value:    normalised (dates YYYY-MM-DD, amounts plain decimals, currency ISO code)
    raw_text: the text exactly as it appears in the document
    """

    value: str | None = None
    raw_text: str | None = None
    page: int | None = None
    source: Literal["extracted", "inferred"] = "extracted"


class RawLineItem(BaseModel):
    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    amount: str | None = None
    raw_text: str | None = None
    page: int | None = None


class RawInvoice(BaseModel):
    invoice_number: RawField = Field(default_factory=RawField)
    invoice_date: RawField = Field(default_factory=RawField)
    supplier_name: RawField = Field(default_factory=RawField)
    customer_name: RawField = Field(default_factory=RawField)
    subtotal: RawField = Field(default_factory=RawField)
    tax: RawField = Field(default_factory=RawField)
    total_amount: RawField = Field(default_factory=RawField)
    currency: RawField = Field(default_factory=RawField)
    tax_rate: RawField = Field(default_factory=RawField)
    line_items: list[RawLineItem] = Field(default_factory=list)


@dataclass
class PageText:
    page_number: int
    text: str
    words: list[Word] = field(default_factory=list)
    ocr_confidence: float | None = None
    method: str = "text_layer"
