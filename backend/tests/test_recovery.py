"""Stalled-document recovery: what happens when a worker dies and its messages are lost."""

from __future__ import annotations

import random
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.db.base import session_scope
from app.devtools import synthetic as syn
from app.tasks import dispatch
from app.tasks.tasks import requeue_stalled_task
from tests.conftest import Uploader


def age(doc_id: str, minutes: int = 60) -> None:
    with session_scope() as s:
        s.execute(
            text("update documents set updated_at = now() - make_interval(mins => :m) where id = :i"),
            {"m": minutes, "i": doc_id},
        )


def test_document_lost_before_processing_is_recovered(
    upload: Uploader, rng: random.Random, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dispatch, "enqueue_start", lambda doc_id: None)  # the message is "lost"
    doc_id = upload.one("lost.pdf", syn.make_pdf([syn.random_invoice(rng, 1)]))
    assert upload.status(doc_id)["status"] == "queued"
    monkeypatch.undo()
    assert requeue_stalled_task.apply().get() == 0  # fresh documents are left alone
    age(doc_id)
    assert requeue_stalled_task.apply().get() == 1
    assert upload.status(doc_id)["status"] == "completed"
    assert requeue_stalled_task.apply().get() == 0  # nothing stalled any more


def test_document_lost_during_extraction_is_recovered(
    upload: Uploader, rng: random.Random, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dispatch, "enqueue_extract", lambda logical_id: None)  # extraction messages lost
    doc_id = upload.one("lost2.pdf", syn.make_pdf([syn.random_invoice(rng, 1), syn.random_invoice(rng, 2)]))
    assert upload.status(doc_id)["status"] == "analyzing"
    monkeypatch.undo()
    age(doc_id)
    assert requeue_stalled_task.apply().get() == 1
    assert upload.status(doc_id)["status"] == "completed"
    events = upload.client.get(f"/api/v1/documents/{doc_id}/history", headers=upload.headers).json()
    assert any(e["stage"] == "recovery" for e in events)


def test_document_lost_during_page_processing_is_recovered(
    upload: Uploader, rng: random.Random, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dispatch, "enqueue_page", lambda *a, **k: None)
    doc_id = upload.one("lost3.pdf", syn.make_pdf([syn.random_invoice(rng, 1)]))
    assert upload.status(doc_id)["status"] == "processing"
    monkeypatch.undo()
    age(doc_id, 30)
    assert requeue_stalled_task.apply().get() == 1
    assert upload.status(doc_id)["status"] == "completed"
    _ = timedelta
