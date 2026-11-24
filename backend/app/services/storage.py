"""File storage behind a small interface. Files are stored by content hash, never by user filename."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from app.core.errors import FileTooLargeError, NotFoundError

_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class TempUpload:
    path: Path
    sha256: str
    size: int


class LocalStorage:
    def __init__(self, base_dir: Path) -> None:
        self.base = base_dir.resolve()
        (self.base / "tmp").mkdir(parents=True, exist_ok=True)
        (self.base / "objects").mkdir(parents=True, exist_ok=True)

    def save_stream(self, stream: BinaryIO, max_bytes: int) -> TempUpload:
        """Stream to a temp file while hashing. Never holds the whole file in memory."""
        tmp = self.base / "tmp" / f"{uuid.uuid4().hex}.part"
        digest = hashlib.sha256()
        size = 0
        try:
            with tmp.open("wb") as out:
                while chunk := stream.read(_CHUNK):
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileTooLargeError(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.")
                    digest.update(chunk)
                    out.write(chunk)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return TempUpload(tmp, digest.hexdigest(), size)

    def commit(self, upload: TempUpload, extension: str) -> str:
        """Move a temp upload to its permanent, content-addressed location. Returns the relative path."""
        ext = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        rel = f"objects/{upload.sha256[:2]}/{upload.sha256[2:4]}/{upload.sha256}{ext}"
        dest = self.base / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            upload.path.unlink(missing_ok=True)
        else:
            shutil.move(str(upload.path), dest)
        return rel

    def discard(self, upload: TempUpload) -> None:
        upload.path.unlink(missing_ok=True)

    def resolve(self, rel: str) -> Path:
        """Absolute path for a stored file, refusing anything outside the storage directory."""
        path = (self.base / rel).resolve()
        if not path.is_relative_to(self.base):
            raise NotFoundError("Stored file path is invalid.")
        if not path.exists():
            raise NotFoundError("Stored file is missing.")
        return path

    def delete(self, rel: str) -> None:
        path = (self.base / rel).resolve()
        if path.is_relative_to(self.base):
            path.unlink(missing_ok=True)
