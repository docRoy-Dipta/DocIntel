"""Manual corrections and approvals. Corrections are stored as separate rows (never overwrite)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.db.models import Correction, Extraction, LineItem, LogicalDocument
from app.services.effective import CORRECTABLE_FIELDS, effective_fields, normalize_input
from app.services.events import audit, log_event
from app.services.pipeline import refresh_document_status
from app.services.validation import validate_logical

_LINE_COLUMNS = {"description": str, "quantity": Decimal, "unit_price": Decimal, "amount": Decimal}


def _logical(session: Session, logical_id: int) -> LogicalDocument:
    logical = session.get(LogicalDocument, logical_id)
    if logical is None:
        raise NotFoundError(f"Logical document {logical_id} not found")
    return logical


def correct_field(
    session: Session,
    settings: Settings,
    *,
    user_id: int,
    logical_id: int,
    field_name: str,
    new_value: str | None,
    reason: str | None,
) -> LogicalDocument:
    logical = _logical(session, logical_id)
    if field_name not in CORRECTABLE_FIELDS:
        raise AppError(f"'{field_name}' cannot be corrected.", code="invalid_field")
    try:
        normalized = normalize_input(field_name, new_value)
    except ValueError as exc:
        raise AppError(str(exc), code="invalid_value") from exc
    old = effective_fields(session, logical_id)[field_name].value
    if normalized == old:
        raise ConflictError("The new value equals the current value.")
    session.add(
        Correction(
            logical_document_id=logical_id,
            target_type="field",
            field_name=field_name,
            old_value=old,
            new_value=normalized,
            reason=reason,
            user_id=user_id,
        )
    )
    logical.review_status = "pending"
    session.flush()
    validate_logical(session, logical_id, settings)
    refresh_document_status(session, logical.document_id)
    log_event(
        session,
        logical.document_id,
        "correction",
        "info",
        f"{field_name}: '{old}' -> '{normalized}'",
        logical_document_id=logical_id,
    )
    audit(
        session,
        user_id=user_id,
        action="correct_field",
        entity_type="logical_document",
        entity_id=logical_id,
        detail={"field": field_name, "old": old, "new": normalized},
    )
    return logical


def correct_line_item(
    session: Session,
    settings: Settings,
    *,
    user_id: int,
    line_item_id: int,
    changes: dict[str, str | None],
    reason: str | None,
) -> LogicalDocument:
    item = session.get(LineItem, line_item_id)
    if item is None:
        raise NotFoundError("Line item not found")
    ext = session.get(Extraction, item.extraction_id)
    assert ext is not None
    if not ext.is_current:
        raise ConflictError("Only line items of the current extraction can be corrected.")
    logical = _logical(session, ext.logical_document_id)
    changed = False
    for col, raw in changes.items():
        if col not in _LINE_COLUMNS:
            raise AppError(f"'{col}' cannot be corrected.", code="invalid_field")
        old = getattr(item, col)
        if col == "description":
            new: object = (raw or "").strip() or None
        else:
            try:
                new = None if raw in (None, "") else Decimal(normalize_input("subtotal", raw) or "")
            except (ValueError, ArithmeticError) as exc:
                raise AppError(f"'{raw}' is not a valid number.", code="invalid_value") from exc
        if new == old:
            continue
        setattr(item, col, new)
        session.add(
            Correction(
                logical_document_id=logical.id,
                target_type="line_item",
                field_name=col,
                line_item_position=item.position,
                old_value=None if old is None else str(old),
                new_value=None if new is None else str(new),
                reason=reason,
                user_id=user_id,
            )
        )
        changed = True
    if not changed:
        raise ConflictError("No change.")
    logical.review_status = "pending"
    session.flush()
    validate_logical(session, logical.id, settings)
    refresh_document_status(session, logical.document_id)
    audit(
        session,
        user_id=user_id,
        action="correct_line_item",
        entity_type="logical_document",
        entity_id=logical.id,
        detail={"position": item.position, "changes": changes},
    )
    return logical


def approve(session: Session, *, user_id: int, logical_id: int) -> LogicalDocument:
    logical = _logical(session, logical_id)
    logical.review_status = "approved"
    logical.needs_review = False
    session.flush()
    refresh_document_status(session, logical.document_id)
    log_event(
        session,
        logical.document_id,
        "review",
        "info",
        "Approved by reviewer",
        logical_document_id=logical_id,
        detail={"validation_status": logical.validation_status},
    )
    audit(
        session,
        user_id=user_id,
        action="approve",
        entity_type="logical_document",
        entity_id=logical_id,
        detail={"validation_status": logical.validation_status},
    )
    return logical
