"""Request id + access log, security headers, rate limiting, upload size guard."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

import jwt
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings
from app.core.ratelimit import RateLimiter

log = logging.getLogger("app.access")
_EXEMPT = ("/health", "/docs", "/openapi.json", "/redoc")


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, limiter: RateLimiter) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.limiter = limiter

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        settings = get_settings()
        started = time.perf_counter()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        path = request.url.path

        limit_error: Response | None = None
        if not path.startswith(_EXEMPT):
            ip = request.client.host if request.client else "unknown"
            key = f"ip:{ip}"
            auth = request.headers.get("authorization", "")
            if auth.lower().startswith("bearer "):
                try:  # rate-limit per user when the token is readable; signature is verified later by auth
                    sub = jwt.decode(auth[7:], options={"verify_signature": False}).get("sub")
                    key = f"user:{sub}"
                except jwt.PyJWTError:
                    pass
            if path.endswith(("/auth/login", "/auth/signup")) and request.method == "POST":
                if not self.limiter.hit(f"login:{ip}", settings.login_rate_limit_per_minute):
                    limit_error = _error(
                        429,
                        "rate_limited",
                        "Too many login attempts. Try again in a minute.",
                        {"Retry-After": "60"},
                    )
            elif not self.limiter.hit(key, settings.rate_limit_per_minute):
                limit_error = _error(429, "rate_limited", "Rate limit exceeded. Slow down.", {"Retry-After": "60"})

        max_body = settings.max_upload_bytes * settings.max_files_per_request + 1024 * 1024
        length = request.headers.get("content-length")
        if limit_error is None and length and length.isdigit() and int(length) > max_body:
            limit_error = _error(413, "request_too_large", "Request body is too large.")

        response = limit_error or await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        log.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "ms": int((time.perf_counter() - started) * 1000),
            },
        )
        return response
