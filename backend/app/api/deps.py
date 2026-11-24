"""FastAPI dependencies: database session, current user, role checks."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ForbiddenError
from app.core.security import decode_access_token
from app.db.base import session_scope
from app.db.models import User

_bearer = HTTPBearer(auto_error=False)


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    role: str


def get_db() -> Iterator[Session]:
    with session_scope() as session:
        yield session


def settings_dep() -> Settings:
    return get_settings()


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> CurrentUser:
    if creds is None:
        raise AuthError("Authentication required.")
    try:
        payload = decode_access_token(creds.credentials, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm)
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise AuthError("Invalid or expired token.") from exc
    if user is None or not user.is_active:
        raise AuthError("Account is disabled or no longer exists.")
    return CurrentUser(user.id, user.email, user.role)


def require_roles(*roles: str) -> Callable[..., CurrentUser]:
    def checker(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in roles:
            raise ForbiddenError("You do not have permission to do this.")
        return user

    checker.allowed_roles = roles  # type: ignore[attr-defined]  # read by scripts/gen_docs.py
    return checker


viewer = require_roles("admin", "reviewer", "viewer")
reviewer = require_roles("admin", "reviewer")
admin = require_roles("admin")
