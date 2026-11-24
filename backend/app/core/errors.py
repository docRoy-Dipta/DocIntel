"""Application exceptions. Services raise these, the API layer turns them into HTTP errors."""

from __future__ import annotations


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class FileRejectedError(AppError):
    """Upload is not acceptable (wrong type, too big, corrupted, encrypted...)."""

    status_code = 422
    code = "file_rejected"


class FileTooLargeError(FileRejectedError):
    status_code = 413
    code = "file_too_large"


class PermanentProcessingError(Exception):
    """A processing failure that retrying will not fix (corrupt page, unsupported content)."""


class TransientProcessingError(Exception):
    """A temporary failure (network, rate limit, timeout). Safe to retry."""
