"""Users and authentication."""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError
from app.core.security import hash_password, verify_password
from app.db.models import User

ROLES = ("admin", "reviewer", "viewer")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Hash of a random password, used so failed logins take the same time whether or not the user exists.
_DUMMY_HASH = hash_password("not-a-real-password")


def create_user(session: Session, email: str, password: str, role: str = "viewer") -> User:
    email = email.strip().lower()
    if not _EMAIL.match(email):
        raise AppError("Invalid email address.")
    if role not in ROLES:
        raise AppError(f"Role must be one of {', '.join(ROLES)}.")
    if len(password) < 10:
        raise AppError("Password must be at least 10 characters.")
    if session.scalar(select(User).where(func.lower(User.email) == email)):
        raise ConflictError("A user with this email already exists.")
    user = User(email=email, password_hash=hash_password(password), role=role)
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, email: str, password: str) -> User | None:
    user = session.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not ok or not user.is_active:
        return None
    return user


def ensure_admin(session: Session, settings: Settings) -> None:
    """Create the first admin from ADMIN_EMAIL / ADMIN_PASSWORD if no admin exists yet."""
    if not (settings.admin_email and settings.admin_password):
        return
    exists = session.scalar(select(func.count()).select_from(User).where(User.role == "admin"))
    if not exists:
        create_user(session, settings.admin_email, settings.admin_password, "admin")
