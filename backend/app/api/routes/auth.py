from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    AuthError,
    CurrentUser,
    admin,
    client_ip,
    current_user,
    get_db,
    settings_dep,
)
from app.core.config import Settings
from app.core.security import create_access_token
from app.db.models import User
from app.schemas.api import LoginRequest, TokenOut, UserCreate, UserOut
from app.services import users
from app.services.events import audit

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenOut)
def login(
    body: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
) -> TokenOut:
    user = users.authenticate(db, body.email, body.password)
    if user is None:
        audit(
            db,
            user_id=None,
            action="login_failed",
            detail={"email": body.email[:200]},
            ip=client_ip(request),
        )
        db.commit()
        raise AuthError("Incorrect email or password.")
    audit(
        db,
        user_id=user.id,
        action="login",
        entity_type="user",
        entity_id=user.id,
        ip=client_ip(request),
    )
    db.commit()
    token = create_access_token(
        subject=str(user.id),
        role=user.role,
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        minutes=settings.access_token_minutes,
    )
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser = Depends(current_user), db: Session = Depends(get_db)) -> User:
    row = db.get(User, user.id)
    assert row is not None
    return row


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    request: Request,
    admin_user: CurrentUser = Depends(admin),
    db: Session = Depends(get_db),
) -> User:
    user = users.create_user(db, body.email, body.password, body.role)
    audit(
        db,
        user_id=admin_user.id,
        action="create_user",
        entity_type="user",
        entity_id=user.id,
        detail={"role": user.role},
        ip=client_ip(request),
    )
    db.commit()
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(_: CurrentUser = Depends(admin), db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)))
