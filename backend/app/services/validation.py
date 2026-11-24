"""Run deterministic validation for one logical document and store the results."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Document, LogicalDocument, ValidationResult
from app.domain.matching import normalize_company, normalize_invoice_number
from app.domain.money import amounts_equal
from app.domain.validation import ERROR, Issue, validate_invoice
from app.services.effective import (
    current_extraction,
    effective_fields,
    refresh_summary,
    to_invoice_data,
)


def find_duplicates(session: Session, logical: LogicalDocument, tolerance: Decimal) -> list[LogicalDocument]:
    """Same supplier + invoice number + total, within the same kind of source (documents vs spreadsheets)."""
    if not logical.invoice_number or logical.doc_type != "invoice":
        return []
    candidates = session.scalars(
        select(LogicalDocument).where(
            LogicalDocument.id != logical.id,
            LogicalDocument.doc_type == "invoice",
            LogicalDocument.source == logical.source,
            func.lower(LogicalDocument.invoice_number) == logical.invoice_number.lower(),
        )
    )
    key = normalize_invoice_number(logical.invoice_number)
    supplier = normalize_company(logical.supplier_name)
    out = []
    for c in candidates:
        if normalize_invoice_number(c.invoice_number) != key:
            continue
        if normalize_company(c.supplier_name) != supplier:
            continue
        both_have_totals = logical.total_amount is not None and c.total_amount is not None
        if both_have_totals and not amounts_equal(logical.total_amount, c.total_amount, tolerance):
            continue
        out.append(c)
    return out


def validate_logical(session: Session, logical_id: int, settings: Settings, *, cascade: bool = True) -> str:
    """Recompute validation results. Returns the validation status (valid|warnings|errors)."""
    logical = session.get(LogicalDocument, logical_id)
    if logical is None:
        raise LookupError(f"logical document {logical_id} not found")
    tolerance = Decimal(settings.amount_tolerance)
    fields = effective_fields(session, logical_id)
    refresh_summary(logical, fields)
    data = to_invoice_data(session, logical, fields, settings)
    report = validate_invoice(data, tolerance=tolerance)
    issues: list[Issue] = list(report.issues)

    duplicates = find_duplicates(session, logical, tolerance)
    if duplicates:
        names = []
        for d in duplicates[:5]:
            doc = session.get(Document, d.document_id)
            names.append(f"{doc.original_filename if doc else d.document_id} (pages {d.start_page}-{d.end_page})")
        issues.append(
            Issue(
                "DUPLICATE_INVOICE",
                ERROR,
                "Another invoice with the same supplier, number and total exists: " + "; ".join(names),
                field="invoice_number",
                actual=logical.invoice_number,
            )
        )

    session.execute(delete(ValidationResult).where(ValidationResult.logical_document_id == logical_id))
    for issue in issues:
        session.add(
            ValidationResult(
                logical_document_id=logical_id,
                rule_code=issue.code,
                severity=issue.severity,
                message=issue.message,
                field=issue.field,
                expected=issue.expected,
                actual=issue.actual,
            )
        )
    status = "errors" if any(i.severity == ERROR for i in issues) else ("warnings" if issues else "valid")
    ext = current_extraction(session, logical_id)
    low_overall = ext is not None and ext.overall_confidence < settings.review_confidence_threshold
    logical.validation_status = status
    logical.needs_review = (status != "valid" or low_overall) and logical.review_status != "approved"
    session.flush()

    if cascade:
        for d in duplicates:  # make sure the earlier copy is flagged too
            validate_logical(session, d.id, settings, cascade=False)
    return status
