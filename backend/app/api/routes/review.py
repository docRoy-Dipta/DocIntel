from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_db, reviewer, settings_dep, viewer
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.db.models import Correction, Document, LogicalDocument, ValidationResult
from app.schemas.api import (
    CorrectionIn,
    CorrectionOut,
    FieldOut,
    InvoiceRow,
    LineItemOut,
    LineItemPatch,
    LogicalOut,
    Paginated,
    ValidationOut,
)
from app.services import corrections as corr
from app.services.effective import current_extraction, current_line_items, effective_fields
from app.services.search import Filters, list_invoices

router = APIRouter(tags=["review"])


def build_logical(db: Session, logical: LogicalDocument) -> LogicalOut:
    ext = current_extraction(db, logical.id)
    fields = effective_fields(db, logical.id)
    doc = db.get(Document, logical.document_id)
    return LogicalOut(
        id=logical.id,
        document_id=logical.document_id,
        filename=doc.original_filename if doc else None,
        position=logical.position,
        doc_type=logical.doc_type,
        start_page=logical.start_page,
        end_page=logical.end_page,
        source=logical.source,
        extraction_status=logical.extraction_status,
        error=logical.error,
        review_status=logical.review_status,
        needs_review=logical.needs_review,
        validation_status=logical.validation_status,
        overall_confidence=ext.overall_confidence if ext else None,
        extraction_version=ext.version if ext else None,
        provider=ext.provider if ext else None,
        fields=[FieldOut(**f.__dict__) for f in fields.values()],
        line_items=[LineItemOut.model_validate(i) for i in current_line_items(db, ext.id if ext else None)],
        validation=[
            ValidationOut.model_validate(v)
            for v in db.scalars(
                select(ValidationResult)
                .where(ValidationResult.logical_document_id == logical.id)
                .order_by(ValidationResult.severity, ValidationResult.id)
            )
        ],
        corrections=[
            CorrectionOut.model_validate(c)
            for c in db.scalars(
                select(Correction).where(Correction.logical_document_id == logical.id).order_by(Correction.id)
            )
        ],
    )


@router.get("/documents/{doc_id}/extractions", response_model=list[LogicalOut])
def document_extractions(
    doc_id: uuid.UUID, _: CurrentUser = Depends(viewer), db: Session = Depends(get_db)
) -> list[LogicalOut]:
    if db.get(Document, doc_id) is None:
        raise NotFoundError("Document not found")
    logicals = db.scalars(
        select(LogicalDocument).where(LogicalDocument.document_id == doc_id).order_by(LogicalDocument.position)
    )
    return [build_logical(db, lg) for lg in logicals]


@router.get("/logical-documents/{logical_id}", response_model=LogicalOut)
def get_logical(logical_id: int, _: CurrentUser = Depends(viewer), db: Session = Depends(get_db)) -> LogicalOut:
    logical = db.get(LogicalDocument, logical_id)
    if logical is None:
        raise NotFoundError("Not found")
    return build_logical(db, logical)


@router.patch("/logical-documents/{logical_id}/fields/{field_name}", response_model=LogicalOut)
def correct_field(
    logical_id: int,
    field_name: str,
    body: CorrectionIn,
    user: CurrentUser = Depends(viewer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> LogicalOut:
    logical = corr.correct_field(
        db,
        settings,
        user_id=user.id,
        logical_id=logical_id,
        field_name=field_name,
        new_value=body.value,
        reason=body.reason,
    )
    db.commit()
    return build_logical(db, logical)


@router.patch("/line-items/{item_id}", response_model=LogicalOut)
def correct_line_item(
    item_id: int,
    body: LineItemPatch,
    user: CurrentUser = Depends(viewer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> LogicalOut:
    changes = body.model_dump(exclude={"reason"}, exclude_unset=True)
    logical = corr.correct_line_item(
        db, settings, user_id=user.id, line_item_id=item_id, changes=changes, reason=body.reason
    )
    db.commit()
    return build_logical(db, logical)


@router.post("/logical-documents/{logical_id}/approve", response_model=LogicalOut)
def approve(logical_id: int, user: CurrentUser = Depends(viewer), db: Session = Depends(get_db)) -> LogicalOut:
    logical = corr.approve(db, user_id=user.id, logical_id=logical_id)
    db.commit()
    return build_logical(db, logical)


@router.get("/invoices", response_model=Paginated)
def invoices(
    supplier: str | None = None,
    customer: str | None = None,
    invoice_number: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    doc_type: str | None = Query(default=None, pattern="^(invoice|receipt|other)$"),
    currency: str | None = Query(default=None, max_length=8),
    min_total: Decimal | None = None,
    max_total: Decimal | None = None,
    needs_review: bool | None = None,
    document_id: uuid.UUID | None = None,
    sort: str = "created_at",
    desc: bool = True,
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    _: CurrentUser = Depends(viewer),
    db: Session = Depends(get_db),
) -> Paginated:
    f = Filters(
        supplier=supplier,
        customer=customer,
        invoice_number=invoice_number,
        date_from=date_from,
        date_to=date_to,
        status=status,
        doc_type=doc_type,
        currency=currency,
        min_total=min_total,
        max_total=max_total,
        needs_review=needs_review,
        document_id=document_id,
    )
    total, rows = list_invoices(db, f, sort=sort, descending=desc, offset=(page - 1) * size, limit=size)
    items: list[Any] = [
        InvoiceRow(
            id=lg.id,
            document_id=lg.document_id,
            filename=name,
            document_status=dstatus,
            doc_type=lg.doc_type,
            start_page=lg.start_page,
            end_page=lg.end_page,
            invoice_number=lg.invoice_number,
            supplier_name=lg.supplier_name,
            customer_name=lg.customer_name,
            invoice_date=lg.invoice_date,
            total_amount=lg.total_amount,
            currency=lg.currency,
            needs_review=lg.needs_review,
            review_status=lg.review_status,
            validation_status=lg.validation_status,
        )
        for lg, name, dstatus in rows
    ]
    return Paginated(items=items, total=total, page=page, size=size)
