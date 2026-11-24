"""Dashboard statistics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Document, LogicalDocument, Page, ProcessingEvent

STATUSES = (
    "uploaded",
    "queued",
    "validating",
    "processing",
    "analyzing",
    "completed",
    "needs_review",
    "failed",
    "rejected",
)


def dashboard(session: Session) -> dict[str, Any]:
    by_status = dict.fromkeys(STATUSES, 0)
    for status, n in session.execute(select(Document.status, func.count()).group_by(Document.status)):
        by_status[status] = n
    total_docs = sum(by_status.values())
    finished = by_status["completed"] + by_status["needs_review"]
    terminal = finished + by_status["failed"] + by_status["rejected"]

    final_events = (
        select(ProcessingEvent.document_id, func.max(ProcessingEvent.created_at).label("done_at"))
        .where(ProcessingEvent.stage == "document", ProcessingEvent.status == "completed")
        .group_by(ProcessingEvent.document_id)
        .subquery()
    )
    avg_seconds = session.scalar(
        select(func.avg(func.extract("epoch", final_events.c.done_at - Document.created_at)))
        .select_from(final_events)
        .join(Document, Document.id == final_events.c.document_id)
    )
    by_type = dict(
        session.execute(select(LogicalDocument.doc_type, func.count()).group_by(LogicalDocument.doc_type)).all()
    )
    review_queue = (
        session.scalar(
            select(func.count())
            .select_from(LogicalDocument)
            .where(LogicalDocument.needs_review.is_(True), LogicalDocument.doc_type != "other")
        )
        or 0
    )
    val = dict(
        session.execute(
            select(LogicalDocument.validation_status, func.count())
            .where(LogicalDocument.doc_type != "other")
            .group_by(LogicalDocument.validation_status)
        ).all()
    )
    pages_total = session.scalar(select(func.count()).select_from(Page).where(Page.status == "done")) or 0
    ocr_pages = session.scalar(select(func.count()).select_from(Page).where(Page.method == "ocr")) or 0
    since = datetime.now(UTC) - timedelta(days=7)
    uploads_7d = session.scalar(select(func.count()).select_from(Document).where(Document.created_at >= since)) or 0
    failures = session.scalars(
        select(Document)
        .where(Document.status.in_(("failed", "rejected")))
        .order_by(Document.updated_at.desc())
        .limit(5)
    )
    return {
        "documents_total": total_docs,
        "by_status": by_status,
        "success_rate": (finished / terminal) if terminal else None,
        "failure_rate": ((by_status["failed"] + by_status["rejected"]) / terminal) if terminal else None,
        "review_queue": review_queue,
        "logical_documents_by_type": by_type,
        "validation_status_counts": val,
        "pages_processed": pages_total,
        "pages_ocr": ocr_pages,
        "uploads_last_7_days": uploads_7d,
        "avg_processing_seconds": float(avg_seconds) if avg_seconds is not None else None,
        "recent_failures": [
            {
                "id": str(d.id),
                "filename": d.original_filename,
                "status": d.status,
                "error": d.error_message,
            }
            for d in failures
        ],
    }
