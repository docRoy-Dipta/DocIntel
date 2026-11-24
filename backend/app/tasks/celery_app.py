"""Celery application: Redis broker, three queues, reliable delivery settings."""

from __future__ import annotations

from celery import Celery
from kombu.entity import Queue

from app.core.config import get_settings
from app.core.logging import configure_logging


def make_celery() -> Celery:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    app = Celery("docint", broker=settings.redis_url, include=["app.tasks.tasks"])
    app.conf.update(
        task_default_queue="parse",
        task_queues=(Queue("parse"), Queue("ocr"), Queue("llm")),
        task_routes={
            "docint.process_page_ocr": {"queue": "ocr"},
            "docint.extract_logical": {"queue": "llm"},
        },
        task_acks_late=True,  # acknowledge only after the task finishes -> redelivered if a worker dies
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,  # long tasks: do not hoard messages
        task_ignore_result=True,  # all state lives in PostgreSQL
        broker_connection_retry_on_startup=True,
        broker_transport_options={"visibility_timeout": 1800},
        beat_schedule={
            "requeue-stalled-documents": {
                "task": "docint.requeue_stalled",
                "schedule": float(settings.requeue_interval_seconds),
            }
        },
        task_always_eager=settings.celery_eager,
        task_eager_propagates=False,
        task_serializer="json",
        accept_content=["json"],
        timezone="UTC",
    )
    return app


celery_app = make_celery()
