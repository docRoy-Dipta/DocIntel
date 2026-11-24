"""Processing history and audit log helpers."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditLog, ProcessingEvent


def log_event(
    session: Session,
    document_id: uuid.UUID,
    stage: str,
    status: str,
    message: str | None = None,
    *,
    detail: Any = None,
    duration_ms: int | None = None,
    logical_document_id: int | None = None,
) -> None:
    session.add(
        ProcessingEvent(
            document_id=document_id,
            logical_document_id=logical_document_id,
            stage=stage,
            status=status,
            message=message,
            detail=detail,
            duration_ms=duration_ms,
        )
    )


def audit(
    session: Session,
    *,
    user_id: int | None,
    action: str,
    entity_type: str | None = None,
    entity_id: object | None = None,
    detail: Any = None,
    ip: str | None = None,
) -> None:
    session.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=None if entity_id is None else str(entity_id),
            detail=detail,
            ip=ip,
        )
    )
