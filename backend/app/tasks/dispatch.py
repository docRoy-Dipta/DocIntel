"""Enqueue helpers. Services and the API call these instead of importing task functions directly."""

from __future__ import annotations

import uuid


def _tasks():  # type: ignore[no-untyped-def]
    from app.tasks import tasks

    return tasks


def enqueue_start(doc_id: uuid.UUID) -> None:
    _tasks().start_document_task.apply_async(args=[str(doc_id)], queue="parse")


def enqueue_page(doc_id: uuid.UUID, page_number: int, *, ocr: bool = False) -> None:
    t = _tasks()
    if ocr:
        t.process_page_ocr_task.apply_async(args=[str(doc_id), page_number], queue="ocr")
    else:
        t.process_page_task.apply_async(args=[str(doc_id), page_number], queue="parse")


def enqueue_spreadsheet(doc_id: uuid.UUID) -> None:
    _tasks().process_spreadsheet_task.apply_async(args=[str(doc_id)], queue="parse")


def enqueue_analyze(doc_id: uuid.UUID) -> None:
    _tasks().analyze_document_task.apply_async(args=[str(doc_id)], queue="parse")


def enqueue_extract(logical_id: int) -> None:
    _tasks().extract_logical_task.apply_async(args=[logical_id], queue="llm")


def enqueue_finalize(doc_id: uuid.UUID) -> None:
    _tasks().finalize_task.apply_async(args=[str(doc_id)], queue="parse")


def dispatch_plan(doc_id: uuid.UUID, plan) -> None:  # type: ignore[no-untyped-def]
    """Enqueue the work described by a ReprocessPlan."""
    if plan.action == "start":
        enqueue_start(doc_id)
    elif plan.action == "pages":
        if plan.spreadsheet:
            enqueue_spreadsheet(doc_id)
        else:
            for n in plan.page_numbers:
                enqueue_page(doc_id, n)
    elif plan.action == "analyze":
        enqueue_analyze(doc_id)
    elif plan.action == "extract":
        for lid in plan.logical_ids:
            enqueue_extract(lid)
    elif plan.action == "finalize":
        enqueue_finalize(doc_id)
