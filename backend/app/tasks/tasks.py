"""Celery tasks: thin wrappers that open a DB session, call a pipeline stage, then enqueue the next.

Rules every task follows:
  * idempotent (safe to run twice),
  * commit BEFORE enqueuing the next stage (so the next worker sees the data),
  * transient errors are retried with exponential backoff, permanent ones are recorded in the database.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from celery import Task

from app.core.config import get_settings
from app.core.errors import TransientProcessingError
from app.db.base import session_scope
from app.db.models import LogicalDocument, Page
from app.services import pipeline
from app.services.extraction import run_extraction
from app.services.runtime import get_embedder_cached, get_extractor_cached, get_storage
from app.tasks import dispatch
from app.tasks.celery_app import celery_app

log = logging.getLogger(__name__)

_RETRY: dict[str, Any] = {
    "autoretry_for": (TransientProcessingError,),
    "retry_backoff": 2,
    "retry_backoff_max": 300,
    "retry_jitter": True,
    "max_retries": 5,
    "acks_late": True,
    "reject_on_worker_lost": True,
}


def _after_pages(doc_id: uuid.UUID) -> None:
    with session_scope() as s:
        claimed = pipeline.maybe_finish_pages(s, doc_id)
    if claimed:
        dispatch.enqueue_analyze(doc_id)


def _finalize(doc_id: uuid.UUID) -> None:
    with session_scope() as s:
        pipeline.finalize_if_complete(s, doc_id)


class PipelineTask(Task):  # type: ignore[misc]
    """Records permanent failures in the database so a document can never hang silently."""

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        log.error("task %s failed: %s", self.name, exc, exc_info=exc)
        try:
            msg = f"{type(exc).__name__}: {exc}"
            if self.name == "docint.extract_logical":
                with session_scope() as s:
                    logical = s.get(LogicalDocument, int(args[0]))
                    doc_id = logical.document_id if logical else None
                    pipeline.fail_logical(s, int(args[0]), msg)
                if doc_id:
                    _finalize(doc_id)
            elif self.name in ("docint.process_page", "docint.process_page_ocr"):
                doc_id = uuid.UUID(args[0])
                with session_scope() as s:
                    pipeline.fail_page(s, doc_id, int(args[1]), msg)
                _after_pages(doc_id)
            elif self.name == "docint.process_spreadsheet":
                doc_id = uuid.UUID(args[0])
                with session_scope() as s:
                    for p in s.query(Page).filter(Page.document_id == doc_id):
                        p.status, p.error = "failed", msg[:500]
                _after_pages(doc_id)
            else:
                with session_scope() as s:
                    pipeline.fail_document(s, uuid.UUID(args[0]), msg)
        except Exception:  # noqa: BLE001
            log.exception("could not record failure for %s", self.name)


@celery_app.task(base=PipelineTask, bind=True, name="docint.start_document", **_RETRY)
def start_document_task(self: Task, doc_id: str) -> None:
    did = uuid.UUID(doc_id)
    with session_scope() as s:
        result = pipeline.start_document(s, get_storage(), get_settings(), did)
    if result.status == "rejected":
        return
    if result.spreadsheet:
        if result.page_numbers:
            dispatch.enqueue_spreadsheet(did)
        else:
            _after_pages(did)
        return
    if not result.page_numbers:
        _after_pages(did)
        return
    for n in result.page_numbers:
        dispatch.enqueue_page(did, n)


@celery_app.task(base=PipelineTask, bind=True, name="docint.process_page", **_RETRY)
def process_page_task(self: Task, doc_id: str, page_number: int) -> None:
    did = uuid.UUID(doc_id)
    with session_scope() as s:
        outcome = pipeline.process_page(s, get_storage(), get_settings(), did, page_number)
    if outcome == "needs_ocr":
        dispatch.enqueue_page(did, page_number, ocr=True)
        return
    _after_pages(did)


@celery_app.task(base=PipelineTask, bind=True, name="docint.process_page_ocr", **_RETRY)
def process_page_ocr_task(self: Task, doc_id: str, page_number: int) -> None:
    did = uuid.UUID(doc_id)
    with session_scope() as s:
        pipeline.process_page(s, get_storage(), get_settings(), did, page_number, force_ocr=True)
    _after_pages(did)


@celery_app.task(base=PipelineTask, bind=True, name="docint.process_spreadsheet", **_RETRY)
def process_spreadsheet_task(self: Task, doc_id: str) -> None:
    did = uuid.UUID(doc_id)
    with session_scope() as s:
        pipeline.process_spreadsheet(s, get_storage(), get_settings(), did)
    _after_pages(did)


@celery_app.task(base=PipelineTask, bind=True, name="docint.analyze_document", **_RETRY)
def analyze_document_task(self: Task, doc_id: str) -> None:
    did = uuid.UUID(doc_id)
    with session_scope() as s:
        result = pipeline.analyze_document(s, get_settings(), did, get_embedder_cached())
    if result.failed:
        return
    if not result.logical_ids:
        _finalize(did)
        return
    for lid in result.logical_ids:
        dispatch.enqueue_extract(lid)


@celery_app.task(base=PipelineTask, bind=True, name="docint.extract_logical", **_RETRY)
def extract_logical_task(self: Task, logical_id: int) -> None:
    with session_scope() as s:
        run_extraction(s, logical_id, get_settings(), get_extractor_cached())
        logical = s.get(LogicalDocument, logical_id)
        doc_id = logical.document_id if logical else None
    if doc_id:
        _finalize(doc_id)


@celery_app.task(base=PipelineTask, bind=True, name="docint.finalize", **_RETRY)
def finalize_task(self: Task, doc_id: str) -> None:
    _finalize(uuid.UUID(doc_id))


@celery_app.task(base=PipelineTask, bind=True, name="docint.requeue_stalled", acks_late=True)
def requeue_stalled_task(self: Task) -> int:
    """Periodic safety net (Celery beat): re-queue documents that stopped making progress."""
    settings = get_settings()
    with session_scope() as s:
        plans = pipeline.stalled_plans(s, timedelta(minutes=settings.stalled_after_minutes))
    for doc_id, plan in plans:
        dispatch.dispatch_plan(doc_id, plan)
    return len(plans)
