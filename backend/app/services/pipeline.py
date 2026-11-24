"""The document processing pipeline, as small idempotent stage functions.

Each function can be run twice safely. Stage hand-off uses atomic "claim" updates
(UPDATE ... WHERE status = X) so that when many workers finish at once, exactly one of them
moves the document to the next stage. State lives in PostgreSQL, so a worker crash loses nothing.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select, update
from sqlalchemy.orm import Session

from app.ai.embeddings import Embedder, chunk_text
from app.core.config import Settings
from app.core.errors import FileRejectedError, NotFoundError, PermanentProcessingError
from app.db.models import (
    Correction,
    Document,
    LogicalDocument,
    Page,
    PageEmbedding,
    ProcessingEvent,
)
from app.processors.classify import split_pages
from app.processors.files import validate_integrity
from app.processors.ocr import OCREngine
from app.processors.pdfpages import ocr_image_frame, ocr_pdf_page, read_pdf_text_layer
from app.processors.spreadsheet import (
    cell_text,
    extract_records,
    read_workbook,
    sheet_to_text,
)
from app.services.events import log_event
from app.services.storage import LocalStorage

SPREADSHEET_KINDS = ("xlsx", "xls", "csv")


@dataclass
class StartResult:
    status: str  # rejected|ready
    page_numbers: list[int] = field(default_factory=list)
    spreadsheet: bool = False


def _get_doc(session: Session, doc_id: uuid.UUID) -> Document:
    doc = session.get(Document, doc_id)
    if doc is None:
        raise NotFoundError(f"Document {doc_id} not found")
    return doc


def _sheet_names(path: object, kind: str) -> list[str]:
    if kind == "csv":
        return ["csv"]
    if kind == "xlsx":
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True)
        try:
            return list(wb.sheetnames)
        finally:
            wb.close()
    import xlrd

    book = xlrd.open_workbook(path, on_demand=True)
    try:
        return list(book.sheet_names())
    finally:
        book.release_resources()


# ----------------------------------------------------------------------------- stage 1: start


def start_document(session: Session, storage: LocalStorage, settings: Settings, doc_id: uuid.UUID) -> StartResult:
    doc = _get_doc(session, doc_id)
    if doc.status not in ("uploaded", "queued", "validating", "failed"):
        return StartResult("ready", [], doc.kind in SPREADSHEET_KINDS)  # already past this stage
    started = time.perf_counter()
    doc.status = "validating"
    doc.error_message = None
    log_event(session, doc.id, "validation", "started")
    session.commit()

    path = storage.resolve(doc.storage_path)
    try:
        info = validate_integrity(path, doc.kind, settings)
    except FileRejectedError as exc:
        doc.status = "rejected"
        doc.error_message = exc.message
        log_event(session, doc.id, "validation", "failed", exc.message)
        return StartResult("rejected")
    for w in info.warnings:
        log_event(session, doc.id, "validation", "warning", w)

    labels = _sheet_names(path, doc.kind) if doc.kind in SPREADSHEET_KINDS else [None] * info.page_count
    existing = {p.page_number: p for p in session.scalars(select(Page).where(Page.document_id == doc.id))}
    for number, label in enumerate(labels, start=1):
        if number not in existing:
            session.add(Page(document_id=doc.id, page_number=number, label=label, status="pending"))
    doc.page_count = len(labels)
    doc.status = "processing"
    session.flush()
    pending = [n for n in range(1, len(labels) + 1) if n not in existing or existing[n].status != "done"]
    log_event(
        session,
        doc.id,
        "validation",
        "completed",
        f"{len(labels)} page(s)/sheet(s)",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return StartResult("ready", pending, doc.kind in SPREADSHEET_KINDS)


# ----------------------------------------------------------------------------- stage 2: pages


def process_page(
    session: Session,
    storage: LocalStorage,
    settings: Settings,
    doc_id: uuid.UUID,
    page_number: int,
    *,
    force_ocr: bool = False,
    engine: OCREngine | None = None,
) -> str:
    """Read one page. Returns done | needs_ocr | failed."""
    page = session.scalar(select(Page).where(Page.document_id == doc_id, Page.page_number == page_number))
    if page is None:
        raise NotFoundError(f"Page {page_number} of {doc_id} not found")
    if page.status == "done" and not force_ocr:
        return "done"
    doc = _get_doc(session, doc_id)
    path = storage.resolve(doc.storage_path)
    started = time.perf_counter()
    try:
        if doc.kind == "pdf":
            result = None if force_ocr else read_pdf_text_layer(path, page_number, settings)
            if result is None:
                if not force_ocr:
                    return "needs_ocr"
                result = ocr_pdf_page(path, page_number, settings, engine)
        else:
            result = ocr_image_frame(path, page_number - 1, settings, engine)
    except PermanentProcessingError as exc:
        page.status, page.error = "failed", str(exc)
        log_event(session, doc.id, "page", "failed", f"Page {page_number}: {exc}")
        return "failed"

    page.text = result.text
    page.char_count = len(result.text)
    page.method = result.method
    page.ocr_confidence = result.ocr_confidence
    page.width, page.height = result.width, result.height
    page.layout = [w.as_list() for w in result.words]
    page.status, page.error = "done", None
    if result.method == "ocr":
        log_event(
            session,
            doc.id,
            "ocr",
            "completed",
            f"Page {page_number}",
            detail={"confidence": result.ocr_confidence},
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    return "done"


def process_spreadsheet(session: Session, storage: LocalStorage, settings: Settings, doc_id: uuid.UUID) -> None:
    """Parse every sheet, store its text, and create one logical document per invoice record found."""
    doc = _get_doc(session, doc_id)
    path = storage.resolve(doc.storage_path)
    started = time.perf_counter()
    try:
        sheets = read_workbook(path, doc.kind, settings)
    except PermanentProcessingError as exc:
        for p in session.scalars(select(Page).where(Page.document_id == doc.id)):
            p.status, p.error = "failed", str(exc)
        log_event(session, doc.id, "spreadsheet", "failed", str(exc))
        return

    has_logicals = (
        session.scalar(select(func.count()).select_from(LogicalDocument).where(LogicalDocument.document_id == doc.id))
        or 0
    )
    position = 0
    for number, sheet in enumerate(sheets, start=1):
        page = session.scalar(select(Page).where(Page.document_id == doc.id, Page.page_number == number))
        if page is None:
            page = Page(document_id=doc.id, page_number=number)
            session.add(page)
        page.label = sheet.name
        page.text = sheet_to_text(sheet)
        page.char_count = len(page.text)
        page.method = "table"
        page.layout = {
            "kind": "sheet",
            "total_rows": len(sheet.rows),
            "rows": [[cell_text(c) for c in row] for row in sheet.rows[:100]],
            "warnings": sheet.warnings,
        }
        page.status, page.error = "done", None
        for w in sheet.warnings:
            log_event(session, doc.id, "spreadsheet", "warning", f"{sheet.name}: {w}")
        records = extract_records(sheet)
        if not records:
            log_event(
                session,
                doc.id,
                "spreadsheet",
                "warning",
                f"Sheet '{sheet.name}': no invoice-like table was recognised.",
            )
        if has_logicals:
            continue  # idempotent retry: logical documents already created
        for rec in records:
            position += 1
            session.add(
                LogicalDocument(
                    document_id=doc.id,
                    position=position,
                    doc_type="invoice",
                    start_page=number,
                    end_page=number,
                    classification_score=10.0,
                    source="spreadsheet",
                    sheet_ref={
                        "sheet": rec.sheet,
                        "first_row": rec.first_row,
                        "last_row": rec.last_row,
                        "fields": {k: {"value": _ser(v.value), "ref": v.ref} for k, v in rec.fields.items()},
                        "has_line_items": rec.has_line_columns,
                        "line_items": [{**{k: _ser(v) for k, v in li.items()}} for li in rec.line_items],
                    },
                )
            )
    log_event(
        session,
        doc.id,
        "spreadsheet",
        "completed",
        f"{len(sheets)} sheet(s), {position} record(s)",
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _ser(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _claimed(result: Any) -> bool:
    """True if an `UPDATE ... WHERE status = X` changed exactly one row (this caller won the claim)."""
    return bool(cast(CursorResult[Any], result).rowcount == 1)


def maybe_finish_pages(session: Session, doc_id: uuid.UUID) -> bool:
    """Update progress and, if every page is finished, atomically claim the move to 'analyzing'.

    Returns True for exactly one caller: the one that should start the analysis stage.
    """
    finished = (
        select(func.count())
        .select_from(Page)
        .where(Page.document_id == doc_id, Page.status.in_(("done", "failed")))
        .scalar_subquery()
    )
    session.execute(update(Document).where(Document.id == doc_id).values(pages_done=finished))
    doc = _get_doc(session, doc_id)
    session.refresh(doc)
    if doc.pages_done < doc.page_count:
        return False
    claim = session.execute(
        update(Document).where(Document.id == doc_id, Document.status == "processing").values(status="analyzing")
    )
    return _claimed(claim)


# ----------------------------------------------------------------------------- stage 3: analyze


@dataclass
class AnalyzeResult:
    logical_ids: list[int]
    failed: bool = False


def index_pages(session: Session, doc_id: uuid.UUID, pages: list[Page], embedder: Embedder) -> int:
    session.execute(delete(PageEmbedding).where(PageEmbedding.document_id == doc_id))
    count = 0
    batch: list[tuple[Page, int, str]] = []

    def flush() -> None:
        nonlocal count
        if not batch:
            return
        vectors = embedder.embed([c for _, _, c in batch])
        for (page, idx, content), vec in zip(batch, vectors, strict=True):
            session.add(
                PageEmbedding(
                    document_id=doc_id,
                    page_id=page.id,
                    page_number=page.page_number,
                    chunk_index=idx,
                    content=content,
                    embedding=vec,
                )
            )
            count += 1
        batch.clear()

    for page in pages:
        for idx, chunk in enumerate(chunk_text(page.text)):
            batch.append((page, idx, chunk))
            if len(batch) >= 64:
                flush()
    flush()
    return count


def _reconcile_split(
    session: Session, doc_id: uuid.UUID, existing: list[LogicalDocument], pages: list[Page]
) -> list[LogicalDocument]:
    """Make the logical documents match the pages that are readable NOW.

    Safe to repeat: unchanged documents keep their id (and therefore their corrections), new ones are
    created, and obsolete ones are removed unless a reviewer already corrected them.
    """
    spans = split_pages([(p.page_number, p.text) for p in pages])
    wanted = {(sp.start_page, sp.end_page, sp.doc_type): sp for sp in spans}
    kept: list[LogicalDocument] = []
    for logical in existing:
        key = (logical.start_page, logical.end_page, logical.doc_type)
        has_corrections = (
            session.scalar(
                select(func.count()).select_from(Correction).where(Correction.logical_document_id == logical.id)
            )
            or 0
        )
        if key in wanted or has_corrections:
            kept.append(logical)
            wanted.pop(key, None)
        else:
            session.delete(logical)
    session.flush()
    for sp in wanted.values():
        row = LogicalDocument(
            document_id=doc_id,
            position=sp.start_page,
            doc_type=sp.doc_type,
            start_page=sp.start_page,
            end_page=sp.end_page,
            classification_score=sp.score,
            source="rules",
        )
        session.add(row)
        kept.append(row)
    session.flush()
    return sorted(kept, key=lambda lg: lg.start_page)


def analyze_document(session: Session, settings: Settings, doc_id: uuid.UUID, embedder: Embedder) -> AnalyzeResult:
    doc = _get_doc(session, doc_id)
    started = time.perf_counter()
    pages = list(
        session.scalars(
            select(Page).where(Page.document_id == doc.id, Page.status == "done").order_by(Page.page_number)
        )
    )
    if not pages:
        doc.status = "failed"
        doc.error_message = "Every page failed to process."
        log_event(session, doc.id, "analysis", "failed", doc.error_message)
        return AnalyzeResult([], failed=True)

    existing = list(
        session.scalars(
            select(LogicalDocument).where(LogicalDocument.document_id == doc.id).order_by(LogicalDocument.position)
        )
    )
    if doc.kind not in SPREADSHEET_KINDS:
        existing = _reconcile_split(session, doc.id, existing, pages)

    embedded = index_pages(session, doc.id, pages, embedder)
    ids: list[int] = []
    for logical in existing:
        if logical.doc_type == "other":
            logical.extraction_status = "skipped"
        elif logical.extraction_status in ("pending", "failed"):
            logical.extraction_status = "pending"
            ids.append(logical.id)
    kinds: dict[str, int] = {}
    for logical in existing:
        kinds[logical.doc_type] = kinds.get(logical.doc_type, 0) + 1
    log_event(
        session,
        doc.id,
        "analysis",
        "completed",
        f"Found {len(existing)} logical document(s): {kinds}; indexed {embedded} chunk(s).",
        detail=kinds,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    return AnalyzeResult(ids)


# ----------------------------------------------------------------------------- stage 4: finalize


def compute_final_status(session: Session, doc_id: uuid.UUID) -> str:
    failed_pages = (
        session.scalar(
            select(func.count()).select_from(Page).where(Page.document_id == doc_id, Page.status == "failed")
        )
        or 0
    )
    logicals = list(session.scalars(select(LogicalDocument).where(LogicalDocument.document_id == doc_id)))
    if failed_pages or any(lg.extraction_status == "failed" for lg in logicals):
        return "needs_review"
    repaired = (
        session.scalar(
            select(func.count())
            .select_from(ProcessingEvent)
            .where(
                ProcessingEvent.document_id == doc_id,
                ProcessingEvent.stage == "validation",
                ProcessingEvent.status == "warning",
                ProcessingEvent.message.like("%repaired%"),
            )
        )
        or 0
    )
    if repaired:  # a repaired file may have silently lost content: a human must look at it
        return "needs_review"
    if any(lg.needs_review for lg in logicals if lg.doc_type != "other"):
        return "needs_review"
    return "completed"


def finalize_if_complete(session: Session, doc_id: uuid.UUID) -> str | None:
    """If every logical document finished extraction, claim the final status. Returns it for one caller."""
    doc = _get_doc(session, doc_id)
    session.refresh(doc)
    if doc.status != "analyzing":
        return None
    pending = (
        session.scalar(
            select(func.count())
            .select_from(LogicalDocument)
            .where(
                LogicalDocument.document_id == doc_id,
                LogicalDocument.extraction_status == "pending",
            )
        )
        or 0
    )
    if pending:
        return None
    final = compute_final_status(session, doc_id)
    claim = session.execute(
        update(Document).where(Document.id == doc_id, Document.status == "analyzing").values(status=final)
    )
    if not _claimed(claim):
        return None
    log_event(session, doc_id, "document", "completed", f"Final status: {final}")
    return final


def refresh_document_status(session: Session, doc_id: uuid.UUID) -> str:
    """Recompute completed/needs_review after a review action (approve, correction)."""
    doc = _get_doc(session, doc_id)
    if doc.status in ("completed", "needs_review"):
        doc.status = compute_final_status(session, doc_id)
    return doc.status


# ----------------------------------------------------------------------------- failure helpers


def fail_document(session: Session, doc_id: uuid.UUID, message: str) -> None:
    doc = session.get(Document, doc_id)
    if doc is None:
        return
    doc.status = "failed"
    doc.error_message = message[:2000]
    log_event(session, doc_id, "document", "failed", message[:2000])


def fail_page(session: Session, doc_id: uuid.UUID, page_number: int, message: str) -> None:
    page = session.scalar(select(Page).where(Page.document_id == doc_id, Page.page_number == page_number))
    if page is not None:
        page.status, page.error = "failed", message[:2000]
    log_event(session, doc_id, "page", "failed", f"Page {page_number}: {message[:500]}")


def fail_logical(session: Session, logical_id: int, message: str) -> None:
    logical = session.get(LogicalDocument, logical_id)
    if logical is None:
        return
    logical.extraction_status, logical.error = "failed", message[:2000]
    log_event(
        session,
        logical.document_id,
        "extraction",
        "failed",
        message[:500],
        logical_document_id=logical_id,
    )


# ----------------------------------------------------------------------------- reprocessing


@dataclass
class ReprocessPlan:
    action: str  # start|pages|analyze|extract|finalize|none
    page_numbers: list[int] = field(default_factory=list)
    logical_ids: list[int] = field(default_factory=list)
    spreadsheet: bool = False


def plan_reprocess(session: Session, doc_id: uuid.UUID, mode: str) -> ReprocessPlan:
    """mode: 'resume' (retry what failed / continue) or 'reextract' (new extraction, keep corrections)."""
    doc = _get_doc(session, doc_id)
    if doc.status in ("uploaded", "queued", "validating", "processing", "analyzing"):
        raise PermanentProcessingError(f"Document is currently '{doc.status}'; wait for it to finish.")
    sheet = doc.kind in SPREADSHEET_KINDS
    if mode == "reextract":
        logicals = list(
            session.scalars(
                select(LogicalDocument).where(
                    LogicalDocument.document_id == doc_id, LogicalDocument.doc_type != "other"
                )
            )
        )
        if not logicals:
            return ReprocessPlan("none")
        for lg in logicals:
            lg.extraction_status = "pending"
        doc.status = "analyzing"
        log_event(session, doc_id, "reprocess", "info", "Re-extraction requested")
        return ReprocessPlan("extract", logical_ids=[lg.id for lg in logicals])

    if doc.status == "rejected":
        raise PermanentProcessingError("Rejected files cannot be reprocessed; upload a corrected file.")
    if doc.page_count == 0:
        doc.status = "queued"
        log_event(session, doc_id, "reprocess", "info", "Restarting from the beginning")
        return ReprocessPlan("start", spreadsheet=sheet)
    session.execute(
        update(Page).where(Page.document_id == doc_id, Page.status == "failed").values(status="pending", error=None)
    )
    pending = [
        p.page_number
        for p in session.scalars(
            select(Page).where(Page.document_id == doc_id, Page.status != "done").order_by(Page.page_number)
        )
    ]
    doc.error_message = None
    if pending:
        doc.status = "processing"
        log_event(session, doc_id, "reprocess", "info", f"Retrying {len(pending)} page(s)")
        return ReprocessPlan("pages", page_numbers=pending, spreadsheet=sheet)
    doc.status = "analyzing"
    log_event(session, doc_id, "reprocess", "info", "Resuming at analysis")
    return ReprocessPlan("analyze")


# ----------------------------------------------------------------------------- stalled documents


def stalled_plans(session: Session, older_than: timedelta) -> list[tuple[uuid.UUID, ReprocessPlan]]:
    """Find documents that stopped making progress (e.g. a worker was killed) and plan how to nudge them.

    Redis keeps a killed worker's un-acknowledged messages hidden until the visibility timeout. Since every
    stage is idempotent, it is safe to simply enqueue the stage again.
    """
    cutoff = datetime.now(UTC) - older_than
    docs = list(
        session.scalars(
            select(Document).where(
                Document.status.in_(("uploaded", "queued", "validating", "processing", "analyzing")),
                Document.updated_at < cutoff,
            )
        )
    )
    plans: list[tuple[uuid.UUID, ReprocessPlan]] = []
    for doc in docs:
        sheet = doc.kind in SPREADSHEET_KINDS
        if doc.status in ("uploaded", "queued", "validating"):
            plan = ReprocessPlan("start", spreadsheet=sheet)
        elif doc.status == "processing":
            pending = [
                p.page_number
                for p in session.scalars(
                    select(Page).where(Page.document_id == doc.id, Page.status == "pending").order_by(Page.page_number)
                )
            ]
            plan = (
                ReprocessPlan("pages", page_numbers=pending, spreadsheet=sheet) if pending else ReprocessPlan("start")
            )
        else:  # analyzing
            logicals = list(session.scalars(select(LogicalDocument).where(LogicalDocument.document_id == doc.id)))
            pending_ids = [lg.id for lg in logicals if lg.extraction_status == "pending" and lg.doc_type != "other"]
            if not logicals:
                plan = ReprocessPlan("analyze")
            elif pending_ids:
                plan = ReprocessPlan("extract", logical_ids=pending_ids)
            else:
                plan = ReprocessPlan("finalize")
        doc.updated_at = datetime.now(UTC)  # do not nudge the same document again until it stalls again
        log_event(session, doc.id, "recovery", "info", f"Stalled in '{doc.status}'; re-queued ({plan.action})")
        plans.append((doc.id, plan))
    return plans
