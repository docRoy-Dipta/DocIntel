from __future__ import annotations

import logging
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, admin, client_ip, get_db, reviewer, settings_dep, viewer
from app.core.config import Settings
from app.core.errors import AppError, FileRejectedError, NotFoundError
from app.db.models import Document, LogicalDocument, Page, ProcessingEvent
from app.processors.pdfpages import render_page_png
from app.schemas.api import (
    DocumentOut,
    DocumentSummaryOut,
    EventOut,
    PageDetailOut,
    PageOut,
    Paginated,
    ReprocessIn,
    StatusOut,
    UploadItemResult,
    UploadResponse,
)
from app.services import pipeline
from app.services.events import audit, log_event
from app.services.ingest import ingest_upload
from app.services.runtime import get_storage
from app.tasks import dispatch

log = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])
_INLINE_KINDS = ("pdf", "image")


def _doc(db: Session, doc_id: uuid.UUID) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise NotFoundError("Document not found")
    return doc


@router.post("/documents", response_model=UploadResponse, status_code=202)
def upload_documents(
    request: Request,
    files: list[UploadFile] = File(...),
    user: CurrentUser = Depends(reviewer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> Any:
    if not files:
        raise AppError("No files were uploaded.")
    if len(files) > settings.max_files_per_request:
        raise AppError(f"At most {settings.max_files_per_request} files per request.", code="too_many_files")
    storage = get_storage()
    results: list[UploadItemResult] = []
    to_start: list[uuid.UUID] = []
    for f in files:
        name = f.filename or "unnamed"
        try:
            outcome = ingest_upload(db, storage, settings, filename=name, stream=f.file, user_id=user.id)
        except FileRejectedError as exc:
            audit(
                db,
                user_id=user.id,
                action="upload_rejected",
                detail={"filename": name[:200], "reason": exc.message},
                ip=client_ip(request),
            )
            results.append(UploadItemResult(filename=name, status="rejected", reason=exc.message))
            continue
        if outcome.status == "accepted":
            doc = db.get(Document, outcome.document_id)
            assert doc is not None
            doc.status = "queued"
            to_start.append(doc.id)
            audit(
                db,
                user_id=user.id,
                action="upload",
                entity_type="document",
                entity_id=doc.id,
                detail={"filename": outcome.filename, "size": doc.size_bytes},
                ip=client_ip(request),
            )
        results.append(
            UploadItemResult(
                filename=outcome.filename,
                status=outcome.status,
                document_id=outcome.document_id,
                reason="Identical file already uploaded." if outcome.status == "duplicate" else None,
            )
        )
    db.commit()  # commit BEFORE enqueuing so workers can see the rows
    for doc_id in to_start:
        dispatch.enqueue_start(doc_id)
    if all(r.status == "rejected" for r in results):
        return JSONResponse(UploadResponse(results=results).model_dump(mode="json"), status_code=422)
    return UploadResponse(results=results)


@router.get("/documents", response_model=Paginated)
def list_documents(
    status: str | None = None,
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    _: CurrentUser = Depends(viewer),
    db: Session = Depends(get_db),
) -> Paginated:
    conds = []
    if status:
        conds.append(Document.status == status)
    if q:
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conds.append(Document.original_filename.ilike(f"%{esc}%", escape="\\"))
    total = db.scalar(select(func.count()).select_from(Document).where(*conds)) or 0
    docs = list(
        db.scalars(
            select(Document).where(*conds).order_by(Document.created_at.desc()).offset((page - 1) * size).limit(size)
        )
    )
    counts: dict[uuid.UUID, tuple[int, int]] = {}
    if docs:
        rows = db.execute(
            select(
                LogicalDocument.document_id,
                func.count(),
                func.count().filter(LogicalDocument.needs_review.is_(True)),
            )
            .where(
                LogicalDocument.document_id.in_([d.id for d in docs]),
                LogicalDocument.doc_type != "other",
            )
            .group_by(LogicalDocument.document_id)
        )
        counts = {r[0]: (r[1], r[2]) for r in rows}
    items = []
    for d in docs:
        inv, rev = counts.get(d.id, (0, 0))
        items.append(
            DocumentSummaryOut.model_validate(d, from_attributes=True).model_copy(
                update={"invoices": inv, "needs_review": rev}
            )
        )
    return Paginated(items=items, total=total, page=page, size=size)


@router.post("/documents/reprocess-failed")
def reprocess_failed(
    request: Request, user: CurrentUser = Depends(reviewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    failed_pages = select(Page.document_id).where(Page.status == "failed")
    failed_logical = select(LogicalDocument.document_id).where(LogicalDocument.extraction_status == "failed")
    docs = list(
        db.scalars(
            select(Document).where(
                or_(
                    Document.status == "failed",
                    (Document.status == "needs_review")
                    & (Document.id.in_(failed_pages) | Document.id.in_(failed_logical)),
                )
            )
        )
    )
    plans = []
    for d in docs:
        try:
            plans.append((d.id, pipeline.plan_reprocess(db, d.id, "resume")))
        except Exception as exc:  # noqa: BLE001 - skip documents that cannot be resumed
            log.info("skipping reprocess of %s: %s", d.id, exc)
            continue
    audit(
        db,
        user_id=user.id,
        action="reprocess_failed",
        detail={"count": len(plans)},
        ip=client_ip(request),
    )
    db.commit()
    for doc_id, plan in plans:
        _dispatch_plan(doc_id, plan)
    return {"requeued": len(plans), "document_ids": [str(i) for i, _ in plans]}


_dispatch_plan = dispatch.dispatch_plan


@router.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: uuid.UUID, _: CurrentUser = Depends(viewer), db: Session = Depends(get_db)) -> Document:
    return _doc(db, doc_id)


@router.delete("/documents/{doc_id}", status_code=204)
def delete_document(
    doc_id: uuid.UUID,
    request: Request,
    user: CurrentUser = Depends(admin),
    db: Session = Depends(get_db),
) -> Response:
    doc = _doc(db, doc_id)
    path, name = doc.storage_path, doc.original_filename
    db.delete(doc)
    audit(
        db,
        user_id=user.id,
        action="delete_document",
        entity_type="document",
        entity_id=doc_id,
        detail={"filename": name},
        ip=client_ip(request),
    )
    db.commit()
    get_storage().delete(path)
    return Response(status_code=204)


@router.get("/documents/{doc_id}/file")
def download_file(
    doc_id: uuid.UUID,
    download: bool = False,
    _: CurrentUser = Depends(viewer),
    db: Session = Depends(get_db),
) -> FileResponse:
    doc = _doc(db, doc_id)
    path = get_storage().resolve(doc.storage_path)
    inline = doc.kind in _INLINE_KINDS and not download
    disposition = f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(doc.original_filename)}"
    return FileResponse(
        path,
        media_type=doc.mime_type,
        headers={
            "Content-Disposition": disposition,
            "Content-Security-Policy": "sandbox; default-src 'none'",  # neutralise any active content in the file
        },
    )


@router.get("/documents/{doc_id}/status", response_model=StatusOut)
def get_status(doc_id: uuid.UUID, _: CurrentUser = Depends(viewer), db: Session = Depends(get_db)) -> StatusOut:
    doc = _doc(db, doc_id)
    total_l = (
        db.scalar(
            select(func.count())
            .select_from(LogicalDocument)
            .where(LogicalDocument.document_id == doc_id, LogicalDocument.doc_type != "other")
        )
        or 0
    )
    done_l = (
        db.scalar(
            select(func.count())
            .select_from(LogicalDocument)
            .where(
                LogicalDocument.document_id == doc_id,
                LogicalDocument.doc_type != "other",
                LogicalDocument.extraction_status.in_(("done", "failed")),
            )
        )
        or 0
    )
    final = doc.status in ("completed", "needs_review", "failed", "rejected")
    if final:
        progress = 1.0
    elif doc.page_count:
        progress = 0.1 + 0.6 * (doc.pages_done / doc.page_count) + (0.3 * done_l / total_l if total_l else 0.0)
    else:
        progress = 0.05
    return StatusOut(
        id=doc.id,
        status=doc.status,
        page_count=doc.page_count,
        pages_done=doc.pages_done,
        progress=round(min(progress, 1.0), 3),
        error_message=doc.error_message,
        logical_documents=total_l,
        extractions_done=done_l,
    )


@router.get("/documents/{doc_id}/history", response_model=list[EventOut])
def get_history(
    doc_id: uuid.UUID,
    limit: int = Query(500, ge=1, le=2000),
    _: CurrentUser = Depends(reviewer),
    db: Session = Depends(get_db),
) -> list[ProcessingEvent]:
    _doc(db, doc_id)
    return list(
        db.scalars(
            select(ProcessingEvent)
            .where(ProcessingEvent.document_id == doc_id)
            .order_by(ProcessingEvent.id)
            .limit(limit)
        )
    )


@router.get("/documents/{doc_id}/pages", response_model=Paginated)
def list_pages(
    doc_id: uuid.UUID,
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    _: CurrentUser = Depends(viewer),
    db: Session = Depends(get_db),
) -> Paginated:
    _doc(db, doc_id)
    total = db.scalar(select(func.count()).select_from(Page).where(Page.document_id == doc_id)) or 0
    rows = db.scalars(
        select(Page).where(Page.document_id == doc_id).order_by(Page.page_number).offset((page - 1) * size).limit(size)
    )
    return Paginated(items=[PageOut.model_validate(r) for r in rows], total=total, page=page, size=size)


def _page(db: Session, doc_id: uuid.UUID, n: int) -> Page:
    p = db.scalar(select(Page).where(Page.document_id == doc_id, Page.page_number == n))
    if p is None:
        raise NotFoundError("Page not found")
    return p


@router.get("/documents/{doc_id}/pages/{page_number}", response_model=PageDetailOut)
def get_page(
    doc_id: uuid.UUID,
    page_number: int,
    _: CurrentUser = Depends(viewer),
    db: Session = Depends(get_db),
) -> Page:
    return _page(db, doc_id, page_number)


@router.get("/documents/{doc_id}/pages/{page_number}/image")
def get_page_image(
    doc_id: uuid.UUID,
    page_number: int,
    dpi: int = Query(110, ge=36, le=200),
    _: CurrentUser = Depends(viewer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> Response:
    doc = _doc(db, doc_id)
    if doc.kind not in _INLINE_KINDS:
        raise AppError("Spreadsheets have no page image; use the page text endpoint.", code="no_image")
    _page(db, doc_id, page_number)
    png = render_page_png(get_storage().resolve(doc.storage_path), doc.kind, page_number, dpi, settings)
    return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.post("/documents/{doc_id}/reprocess", status_code=202)
def reprocess(
    doc_id: uuid.UUID,
    body: ReprocessIn,
    request: Request,
    user: CurrentUser = Depends(reviewer),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _doc(db, doc_id)
    try:
        plan = pipeline.plan_reprocess(db, doc_id, body.mode)
    except Exception as exc:
        raise AppError(str(exc), code="cannot_reprocess") from exc
    log_event(
        db,
        doc_id,
        "reprocess",
        "info",
        f"Requested by user {user.id} (mode={body.mode}, action={plan.action})",
    )
    audit(
        db,
        user_id=user.id,
        action="reprocess",
        entity_type="document",
        entity_id=doc_id,
        detail={"mode": body.mode, "action": plan.action},
        ip=client_ip(request),
    )
    db.commit()
    _dispatch_plan(doc_id, plan)
    return {"document_id": str(doc_id), "action": plan.action}
