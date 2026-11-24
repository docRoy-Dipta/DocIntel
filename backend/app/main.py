"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.middleware import SecurityMiddleware
from app.api.routes import auth, documents, misc, review
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.ratelimit import build_limiter
from app.db.base import session_scope
from app.services.users import ensure_admin

log = logging.getLogger(__name__)


def _envelope(status: int, code: str, message: str, details: object = None) -> JSONResponse:
    body: dict[str, object] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details  # type: ignore[index]
    return JSONResponse(body, status_code=status)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            with session_scope() as s:
                ensure_admin(s, settings)
        except Exception:  # noqa: BLE001 - e.g. migrations not applied yet; the API still starts
            log.exception("could not ensure the admin user")
        yield

    app = FastAPI(title="Document Intelligence API", version=__version__, lifespan=lifespan)
    limiter = build_limiter(None if settings.celery_eager else settings.redis_url)
    app.add_middleware(SecurityMiddleware, limiter=limiter)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return _envelope(exc.status_code, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _envelope(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"]} for e in exc.errors()]
        return _envelope(422, "validation_error", "The request is invalid.", details)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error", exc_info=exc)
        return _envelope(500, "internal_error", "Something went wrong on the server.")

    app.include_router(misc.health_router)  # /health, /health/ready (unversioned, for load balancers)
    prefix = "/api/v1"
    app.include_router(auth.router, prefix=prefix)
    app.include_router(documents.router, prefix=prefix)
    app.include_router(review.router, prefix=prefix)
    app.include_router(misc.router, prefix=prefix)
    return app


app = create_app()
