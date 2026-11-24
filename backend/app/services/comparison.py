"""Cross-document verification: build comparable records, match them, store the evidence."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.db.models import Comparison, ComparisonItem, Document, LogicalDocument
from app.domain.matching import (
    MATCH,
    MISMATCH,
    MISSING_LEFT,
    MISSING_RIGHT,
    UNCERTAIN,
    FieldValue,
    Record,
    RecordPair,
    match_records,
)
from app.services.effective import current_extraction, current_line_items, effective_fields
from app.services.events import audit

_AMOUNTS = {"subtotal", "tax", "total_amount"}


def _typed(name: str, value: str | None) -> Any:
    if value in (None, ""):
        return None
    if name in _AMOUNTS:
        return Decimal(value)
    if name == "invoice_date":
        return date.fromisoformat(value)
    return value


def records_for_document(session: Session, document_id: uuid.UUID) -> list[Record]:
    doc = session.get(Document, document_id)
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")
    logicals = session.scalars(
        select(LogicalDocument)
        .where(
            LogicalDocument.document_id == document_id,
            LogicalDocument.doc_type.in_(("invoice", "receipt")),
            LogicalDocument.extraction_status == "done",
        )
        .order_by(LogicalDocument.position)
    )
    out: list[Record] = []
    for logical in logicals:
        fields = effective_fields(session, logical.id)
        ref = {
            "logical_id": logical.id,
            "document_id": str(document_id),
            "filename": doc.original_filename,
            "doc_type": logical.doc_type,
            "pages": [logical.start_page, logical.end_page],
            "kind": doc.kind,
        }
        rec = Record(ref=ref)
        for name, f in fields.items():
            if name == "tax_rate" or f.value is None:
                continue
            src: dict[str, Any] = {
                "filename": doc.original_filename,
                "document_id": str(document_id),
                "logical_id": logical.id,
                "page": f.page,
                "raw_text": f.raw_text,
                "corrected": f.corrected,
            }
            if isinstance(f.bbox, dict):  # spreadsheet evidence
                src.update({"sheet": f.bbox.get("sheet"), "cell": f.bbox.get("cell")})
            elif f.bbox:
                src["bbox"] = f.bbox
            try:
                rec.fields[name] = FieldValue(_typed(name, f.value), src)
            except (ValueError, ArithmeticError):
                continue
        ext = current_extraction(session, logical.id)
        rec.line_items = [
            {
                "description": i.description,
                "quantity": i.quantity,
                "unit_price": i.unit_price,
                "amount": i.amount,
            }
            for i in current_line_items(session, ext.id if ext else None)
        ]
        out.append(rec)
    return out


def _pair_status(pair: RecordPair) -> str:
    if pair.left is None or pair.right is None:
        return "unmatched"
    verdicts = {c.verdict for c in pair.comparisons}
    if verdicts & {MISMATCH, MISSING_LEFT, MISSING_RIGHT}:
        return "discrepancy"
    if UNCERTAIN in verdicts:
        return "uncertain"
    return "match"


def _jsonable(v: object) -> object:
    return str(v) if isinstance(v, Decimal | date) else v


def _label(record: Record) -> str:
    number = record.fields.get("invoice_number")
    return str(number.value) if number else "(no number)"


def create_comparison(session: Session, *, user_id: int, left_id: uuid.UUID, right_id: uuid.UUID) -> Comparison:
    if left_id == right_id:
        raise AppError("Choose two different documents to compare.")
    left = records_for_document(session, left_id)
    right = records_for_document(session, right_id)
    if not left or not right:
        raise AppError(
            "Both documents need at least one extracted invoice or receipt before they can be compared.",
            code="nothing_to_compare",
        )
    pairs = match_records(left, right)
    comp = Comparison(left_document_id=left_id, right_document_id=right_id, created_by_id=user_id)
    session.add(comp)
    session.flush()
    summary = {
        "pairs": 0,
        "match": 0,
        "discrepancy": 0,
        "uncertain": 0,
        "unmatched_left": 0,
        "unmatched_right": 0,
        "mismatched_fields": 0,
    }
    for idx, pair in enumerate(pairs):
        status = _pair_status(pair)
        if status == "unmatched":
            summary["unmatched_left" if pair.right is None else "unmatched_right"] += 1
        else:
            summary["pairs"] += 1
            summary[status] += 1
        summary["mismatched_fields"] += sum(1 for c in pair.comparisons if c.verdict == MISMATCH)
        for c in pair.comparisons:
            session.add(
                ComparisonItem(
                    comparison_id=comp.id,
                    pair_index=idx,
                    left_logical_id=pair.left.ref["logical_id"] if pair.left else None,
                    right_logical_id=pair.right.ref["logical_id"] if pair.right else None,
                    field=c.field,
                    left_value=c.left_value,
                    right_value=c.right_value,
                    left_source={k: _jsonable(v) for k, v in c.left_source.items()},
                    right_source={k: _jsonable(v) for k, v in c.right_source.items()},
                    verdict=c.verdict,
                    rule=f"[{pair.matched_by}] {c.rule}",
                )
            )
        if pair.left is None or pair.right is None:  # explicit row for the unmatched record
            side = pair.left or pair.right
            assert side is not None
            session.add(
                ComparisonItem(
                    comparison_id=comp.id,
                    pair_index=idx,
                    left_logical_id=pair.left.ref["logical_id"] if pair.left else None,
                    right_logical_id=pair.right.ref["logical_id"] if pair.right else None,
                    field="record",
                    left_value=None,
                    right_value=None,
                    left_source={},
                    right_source={},
                    verdict=MISSING_RIGHT if pair.right is None else MISSING_LEFT,
                    rule=f"No matching record found in the other document: {_label(side)}",
                )
            )
    comp.summary = summary
    audit(
        session,
        user_id=user_id,
        action="compare",
        entity_type="comparison",
        entity_id=comp.id,
        detail={"left": str(left_id), "right": str(right_id), **summary},
    )
    return comp


def comparison_detail(session: Session, comparison_id: int) -> dict[str, Any]:
    comp = session.get(Comparison, comparison_id)
    if comp is None:
        raise NotFoundError("Comparison not found")
    items = list(
        session.scalars(
            select(ComparisonItem)
            .where(ComparisonItem.comparison_id == comparison_id)
            .order_by(ComparisonItem.pair_index, ComparisonItem.id)
        )
    )
    left = session.get(Document, comp.left_document_id) if comp.left_document_id else None
    right = session.get(Document, comp.right_document_id) if comp.right_document_id else None
    groups: dict[int, dict[str, Any]] = {}
    for it in items:
        g = groups.setdefault(
            it.pair_index,
            {
                "pair_index": it.pair_index,
                "left_logical_id": it.left_logical_id,
                "right_logical_id": it.right_logical_id,
                "items": [],
            },
        )
        g["items"].append(
            {
                "field": it.field,
                "left_value": it.left_value,
                "right_value": it.right_value,
                "left_source": it.left_source,
                "right_source": it.right_source,
                "verdict": it.verdict,
                "rule": it.rule,
            }
        )
    for g in groups.values():
        verdicts = {i["verdict"] for i in g["items"] if i["field"] != "record"}
        if g["left_logical_id"] is None or g["right_logical_id"] is None:
            g["status"] = "unmatched"
        elif verdicts & {MISMATCH, MISSING_LEFT, MISSING_RIGHT}:
            g["status"] = "discrepancy"
        elif UNCERTAIN in verdicts:
            g["status"] = "uncertain"
        else:
            g["status"] = MATCH
    return {
        "id": comp.id,
        "created_at": comp.created_at,
        "summary": comp.summary,
        "left": {"id": comp.left_document_id, "filename": left.original_filename if left else None},
        "right": {
            "id": comp.right_document_id,
            "filename": right.original_filename if right else None,
        },
        "pairs": list(groups.values()),
    }
