"""Request/response models for the REST API."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    email: str
    password: str = Field(min_length=10)


class UserOut(ORM):
    id: int
    email: str
    role: str
    is_active: bool


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=10)
    role: str = "viewer"


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105
    user: UserOut


class DocumentOut(ORM):
    id: uuid.UUID
    original_filename: str
    kind: str
    mime_type: str
    size_bytes: int
    status: str
    page_count: int
    pages_done: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DocumentSummaryOut(DocumentOut):
    invoices: int = 0
    needs_review: int = 0


class Paginated(BaseModel):
    items: list[Any]
    total: int
    page: int
    size: int


class UploadItemResult(BaseModel):
    filename: str
    status: str  # accepted|duplicate|rejected
    document_id: uuid.UUID | None = None
    reason: str | None = None


class UploadResponse(BaseModel):
    results: list[UploadItemResult]


class StatusOut(BaseModel):
    id: uuid.UUID
    status: str
    page_count: int
    pages_done: int
    progress: float
    error_message: str | None
    logical_documents: int
    extractions_done: int


class EventOut(ORM):
    id: int
    stage: str
    status: str
    message: str | None
    detail: Any = None
    duration_ms: int | None
    logical_document_id: int | None
    created_at: datetime


class PageOut(ORM):
    page_number: int
    label: str | None
    status: str
    method: str | None
    char_count: int
    ocr_confidence: float | None
    width: float | None
    height: float | None
    error: str | None


class PageDetailOut(PageOut):
    text: str
    layout: Any = None


class FieldOut(BaseModel):
    name: str
    value: str | None
    original_value: str | None
    corrected: bool
    confidence: float
    source: str
    grounded: bool
    page: int | None
    bbox: Any = None
    raw_text: str | None


class LineItemOut(ORM):
    id: int
    position: int
    description: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None
    page: int | None
    raw_text: str | None
    bbox: Any = None
    confidence: float


class ValidationOut(ORM):
    rule_code: str
    severity: str
    message: str
    field: str | None
    expected: str | None
    actual: str | None


class CorrectionOut(ORM):
    id: int
    target_type: str
    field_name: str
    line_item_position: int | None
    old_value: str | None
    new_value: str | None
    reason: str | None
    user_id: int | None
    created_at: datetime


class LogicalOut(BaseModel):
    id: int
    document_id: uuid.UUID
    filename: str | None = None
    position: int
    doc_type: str
    start_page: int
    end_page: int
    source: str
    extraction_status: str
    error: str | None
    review_status: str
    needs_review: bool
    validation_status: str
    overall_confidence: float | None
    extraction_version: int | None
    provider: str | None
    fields: list[FieldOut]
    line_items: list[LineItemOut]
    validation: list[ValidationOut]
    corrections: list[CorrectionOut]


class InvoiceRow(BaseModel):
    id: int
    document_id: uuid.UUID
    filename: str
    document_status: str
    doc_type: str
    start_page: int
    end_page: int
    invoice_number: str | None
    supplier_name: str | None
    customer_name: str | None
    invoice_date: date | None
    total_amount: Decimal | None
    currency: str | None
    needs_review: bool
    review_status: str
    validation_status: str


class CorrectionIn(BaseModel):
    value: str | None = None
    reason: str | None = Field(default=None, max_length=1000)


class LineItemPatch(BaseModel):
    description: str | None = None
    quantity: str | None = None
    unit_price: str | None = None
    amount: str | None = None
    reason: str | None = Field(default=None, max_length=1000)


class ReprocessIn(BaseModel):
    mode: str = Field(default="resume", pattern="^(resume|reextract)$")


class ComparisonIn(BaseModel):
    left_document_id: uuid.UUID
    right_document_id: uuid.UUID


class SearchHitOut(BaseModel):
    document_id: uuid.UUID
    filename: str
    page_number: int
    score: float
    snippet: str
    sources: list[str]
    logical: dict[str, Any] | None = None
