"""Run extraction for one logical document: extract -> ground -> score -> persist -> validate."""

from __future__ import annotations

import time
from decimal import Decimal
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.ai.extractor import Extractor, extract_document
from app.ai.schemas import FIELD_NAMES, REQUIRED_FIELDS, PageText
from app.ai.scoring import FieldResult, LineResult, ScoredInvoice, score_extraction
from app.core.config import Settings
from app.core.errors import PermanentProcessingError
from app.db.models import Document, ExtractedField, Extraction, LineItem, LogicalDocument, Page
from app.domain.money import parse_amount
from app.processors.layout import Word
from app.services.events import log_event
from app.services.validation import validate_logical


def load_page_texts(session: Session, document_id: object, start: int, end: int) -> list[PageText]:
    pages = session.scalars(
        select(Page)
        .where(
            Page.document_id == document_id,
            Page.page_number.between(start, end),
            Page.status == "done",
        )
        .order_by(Page.page_number)
    )
    out = []
    for p in pages:
        words = [Word.from_list(w) for w in p.layout] if isinstance(p.layout, list) else []
        out.append(PageText(p.page_number, p.text, words, p.ocr_confidence, p.method or "text_layer"))
    return out


def _scored_from_sheet(logical: LogicalDocument) -> ScoredInvoice:
    ref: dict[str, Any] = logical.sheet_ref or {}
    fields: dict[str, FieldResult] = {}
    for name in FIELD_NAMES:
        cell = (ref.get("fields") or {}).get(name)
        if cell is None:
            fields[name] = FieldResult(name, None, None, None, None, "extracted", 0.0, True)
        else:
            fields[name] = FieldResult(
                name,
                str(cell["value"]),
                str(cell["value"]),
                logical.start_page,
                {"sheet": ref.get("sheet"), "cell": cell["ref"]},
                "extracted",
                0.98,
                True,
            )
    lines = [
        LineResult(
            position=i + 1,
            description=li.get("description"),
            quantity=parse_amount(li.get("quantity")),
            unit_price=parse_amount(li.get("unit_price")),
            amount=parse_amount(li.get("amount")),
            page=logical.start_page,
            raw_text=None,
            bbox={"sheet": ref.get("sheet"), "cell": li.get("ref")},
            confidence=0.98,
        )
        for i, li in enumerate(ref.get("line_items") or [])
    ]
    req = [fields[n].confidence for n in REQUIRED_FIELDS]
    return ScoredInvoice(fields, lines, [], round(sum(req) / len(req), 3))


def run_extraction(session: Session, logical_id: int, settings: Settings, extractor: Extractor) -> None:
    """Extract and persist a new version. Raises TransientProcessingError (retry) but handles permanent failures."""
    logical = session.get(LogicalDocument, logical_id)
    if logical is None:
        raise LookupError(f"logical document {logical_id} not found")
    doc = session.get(Document, logical.document_id)
    assert doc is not None
    if logical.doc_type == "other":
        logical.extraction_status = "skipped"
        return

    started = time.perf_counter()
    log_event(
        session,
        doc.id,
        "extraction",
        "started",
        f"Pages {logical.start_page}-{logical.end_page}",
        logical_document_id=logical.id,
    )
    usage: dict[str, int] = {}
    try:
        if logical.source == "spreadsheet":
            scored = _scored_from_sheet(logical)
            raw_json: dict[str, Any] = {"sheet_ref": logical.sheet_ref}
            provider, model = "spreadsheet-mapper", None
        else:
            pages = load_page_texts(session, doc.id, logical.start_page, logical.end_page)
            if not pages:
                raise PermanentProcessingError("No readable pages for this document.")
            raw, usage = extract_document(extractor, pages, logical.doc_type)
            scored = score_extraction(raw, pages)
            raw_json = {
                "raw": raw.model_dump(),
                "rejected_fields": {n: f.rejected_value for n, f in scored.fields.items() if f.rejected_value},
                "rejected_lines": scored.rejected_lines,
            }
            provider, model = extractor.name, extractor.model
    except PermanentProcessingError as exc:
        logical.extraction_status = "failed"
        logical.error = str(exc)
        log_event(session, doc.id, "extraction", "failed", str(exc), logical_document_id=logical.id)
        return

    version = (
        session.scalar(
            select(Extraction.version)
            .where(Extraction.logical_document_id == logical.id)
            .order_by(Extraction.version.desc())
        )
        or 0
    ) + 1
    session.execute(update(Extraction).where(Extraction.logical_document_id == logical.id).values(is_current=False))
    ext = Extraction(
        logical_document_id=logical.id,
        version=version,
        provider=provider,
        model=model,
        prompt_version=settings.prompt_version,
        raw_json=raw_json,
        overall_confidence=scored.overall_confidence,
        is_current=True,
        duration_ms=int((time.perf_counter() - started) * 1000),
        usage=usage or None,
    )
    session.add(ext)
    session.flush()
    for name in FIELD_NAMES:
        f = scored.fields[name]
        session.add(
            ExtractedField(
                extraction_id=ext.id,
                name=name,
                value=f.value,
                raw_text=f.raw_text,
                page=f.page,
                bbox=f.bbox,
                source=f.source,
                confidence=f.confidence,
                grounded=f.grounded,
            )
        )
    for li in scored.line_items:
        session.add(
            LineItem(
                extraction_id=ext.id,
                position=li.position,
                description=li.description,
                quantity=li.quantity,
                unit_price=li.unit_price,
                amount=li.amount,
                page=li.page,
                raw_text=li.raw_text,
                bbox=li.bbox,
                confidence=li.confidence,
            )
        )
    logical.extraction_status = "done"
    logical.error = None
    session.flush()
    status = validate_logical(session, logical.id, settings)
    log_event(
        session,
        doc.id,
        "extraction",
        "completed",
        f"v{version}: confidence {scored.overall_confidence:.2f}, validation {status}",
        detail={"line_items": len(scored.line_items), "usage": usage},
        duration_ms=int((time.perf_counter() - started) * 1000),
        logical_document_id=logical.id,
    )


def _unused(_: Decimal) -> None:  # keeps Decimal import explicit for type checkers
    return None
