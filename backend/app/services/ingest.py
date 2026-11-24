"""Upload intake: stream to disk, hash, detect real file type, de-duplicate, create the document row."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import FileRejectedError
from app.db.models import Document
from app.processors.files import detect_kind
from app.services.events import log_event
from app.services.storage import LocalStorage


@dataclass(frozen=True)
class UploadOutcome:
    filename: str
    status: str  # accepted|duplicate
    document_id: uuid.UUID
    existing_status: str | None = None


def sanitize_filename(name: str) -> str:
    """Keep only the final path component and printable characters. Used for display only."""
    base = Path(name.replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip().strip(".")
    return (base or "unnamed")[:255]


def ingest_upload(
    session: Session,
    storage: LocalStorage,
    settings: Settings,
    *,
    filename: str,
    stream: BinaryIO,
    user_id: int | None,
) -> UploadOutcome:
    """Raises FileRejectedError (or a subclass) when the file cannot be accepted."""
    safe_name = sanitize_filename(filename)
    upload = storage.save_stream(stream, settings.max_upload_bytes)
    try:
        kind = detect_kind(upload.path, safe_name, settings)
    except FileRejectedError:
        storage.discard(upload)
        raise

    existing = session.scalar(select(Document).where(Document.sha256 == upload.sha256))
    if existing is not None:
        storage.discard(upload)
        return UploadOutcome(safe_name, "duplicate", existing.id, existing.status)

    rel = storage.commit(upload, Path(safe_name).suffix)
    doc = Document(
        original_filename=safe_name,
        kind=kind.kind,
        mime_type=kind.mime,
        size_bytes=upload.size,
        sha256=upload.sha256,
        storage_path=rel,
        status="uploaded",
        uploaded_by_id=user_id,
    )
    session.add(doc)
    session.flush()
    log_event(session, doc.id, "upload", "completed", f"Stored {upload.size} bytes as {kind.kind}.")
    return UploadOutcome(safe_name, "accepted", doc.id)
