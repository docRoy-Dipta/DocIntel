from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, admin, client_ip, get_db, reviewer, settings_dep, viewer
from app.core.config import Settings
from app.db.models import AuditLog
from app.schemas.api import ComparisonIn, SearchHitOut
from app.services import comparison as cmp
from app.services import stats
from app.services.runtime import get_embedder_cached
from app.services.search import Filters, search_pages

router = APIRouter()
health_router = APIRouter(tags=["health"])


@health_router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@health_router.get("/health/ready")
def ready(
    db: Annotated[Session, Depends(get_db)],
    settings: Settings = Depends(settings_dep),
) -> dict[str, Any]:
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"
    if settings.celery_eager:
        checks["redis"] = "skipped (eager mode)"
    else:
        try:
            import redis

            redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1).ping()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {type(exc).__name__}"
    ok = all(v == "ok" or v.startswith("skipped") for v in checks.values())
    from fastapi.responses import JSONResponse

    return JSONResponse(
        {"status": "ready" if ok else "unavailable", "checks": checks},
        status_code=200 if ok else 503,
    )  # type: ignore[return-value]


@router.get("/search", response_model=list[SearchHitOut], tags=["search"])
def search(
    q: str = Query(min_length=1, max_length=300),
    mode: str = Query("hybrid", pattern="^(keyword|semantic|hybrid)$"),
    supplier: str | None = None,
    customer: str | None = None,
    invoice_number: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    status: str | None = None,
    doc_type: str | None = Query(default=None, pattern="^(invoice|receipt|other)$"),
    currency: str | None = Query(default=None, max_length=8),
    min_total: Decimal | None = None,
    max_total: Decimal | None = None,
    needs_review: bool | None = None,
    limit: int = Query(20, ge=1, le=100),
    _: CurrentUser = Depends(viewer),
    db: Session = Depends(get_db),
) -> Any:
    f = Filters(
        supplier=supplier,
        customer=customer,
        invoice_number=invoice_number,
        date_from=date_from,
        date_to=date_to,
        status=status,
        doc_type=doc_type,
        currency=currency,
        min_total=min_total,
        max_total=max_total,
        needs_review=needs_review,
    )
    hits = search_pages(db, get_embedder_cached(), q, mode, f, limit)
    return [
        SearchHitOut(
            document_id=h.document_id,
            filename=h.filename,
            page_number=h.page_number,
            score=round(h.score, 5),
            snippet=h.snippet,
            sources=h.sources,
            logical=h.logical,
        )
        for h in hits
    ]


@router.post("/comparisons", status_code=201, tags=["comparisons"])
def create_comparison(
    body: ComparisonIn,
    request: Request,
    user: CurrentUser = Depends(reviewer),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    comp = cmp.create_comparison(db, user_id=user.id, left_id=body.left_document_id, right_id=body.right_document_id)
    db.commit()
    return cmp.comparison_detail(db, comp.id)


@router.get("/comparisons", tags=["comparisons"])
def list_comparisons(
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    _: CurrentUser = Depends(viewer),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from sqlalchemy import func

    from app.db.models import Comparison, Document

    total = db.scalar(select(func.count()).select_from(Comparison)) or 0
    rows = db.scalars(select(Comparison).order_by(Comparison.id.desc()).offset((page - 1) * size).limit(size))
    items = []
    for c in rows:
        lg = db.get(Document, c.left_document_id) if c.left_document_id else None
        r = db.get(Document, c.right_document_id) if c.right_document_id else None
        items.append(
            {
                "id": c.id,
                "created_at": c.created_at,
                "summary": c.summary,
                "left": lg.original_filename if lg else None,
                "right": r.original_filename if r else None,
            }
        )
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/comparisons/{comparison_id}", tags=["comparisons"])
def get_comparison(
    comparison_id: int, _: CurrentUser = Depends(viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return cmp.comparison_detail(db, comparison_id)


@router.get("/stats/dashboard", tags=["stats"])
def dashboard(_: CurrentUser = Depends(viewer), db: Session = Depends(get_db)) -> dict[str, Any]:
    return stats.dashboard(db)


@router.get("/audit-log", tags=["admin"])
def audit_log(
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    _: CurrentUser = Depends(admin),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).offset((page - 1) * size).limit(size))
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "detail": r.detail,
            "ip": r.ip,
            "created_at": r.created_at,
        }
        for r in rows
    ]


_ = (client_ip, uuid)
