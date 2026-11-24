"""Keyword (PostgreSQL full-text), semantic (pgvector) and hybrid (reciprocal rank fusion) search."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, desc, exists, func, literal, literal_column, select
from sqlalchemy.orm import Session

from app.ai.embeddings import Embedder
from app.db.models import Document, LogicalDocument, Page, PageEmbedding

_EN: Any = literal_column("'english'")
HIGHLIGHT = "MaxWords=35, MinWords=12, MaxFragments=1, StartSel=[[[, StopSel=]]]"


@dataclass
class Filters:
    supplier: str | None = None
    customer: str | None = None
    invoice_number: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    status: str | None = None
    doc_type: str | None = None
    currency: str | None = None
    min_total: Decimal | None = None
    max_total: Decimal | None = None
    needs_review: bool | None = None
    document_id: uuid.UUID | None = None

    def logical_conditions(self) -> list[Any]:
        c: list[Any] = []
        if self.supplier:
            c.append(LogicalDocument.supplier_name.ilike(f"%{_esc(self.supplier)}%", escape="\\"))
        if self.customer:
            c.append(LogicalDocument.customer_name.ilike(f"%{_esc(self.customer)}%", escape="\\"))
        if self.invoice_number:
            c.append(LogicalDocument.invoice_number.ilike(f"%{_esc(self.invoice_number)}%", escape="\\"))
        if self.date_from:
            c.append(LogicalDocument.invoice_date >= self.date_from)
        if self.date_to:
            c.append(LogicalDocument.invoice_date <= self.date_to)
        if self.doc_type:
            c.append(LogicalDocument.doc_type == self.doc_type)
        if self.currency:
            c.append(LogicalDocument.currency == self.currency.upper())
        if self.min_total is not None:
            c.append(LogicalDocument.total_amount >= self.min_total)
        if self.max_total is not None:
            c.append(LogicalDocument.total_amount <= self.max_total)
        if self.needs_review is not None:
            c.append(LogicalDocument.needs_review.is_(self.needs_review))
        return c


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass
class Hit:
    document_id: uuid.UUID
    filename: str
    page_number: int
    score: float
    snippet: str
    logical: dict[str, Any] | None = None
    sources: list[str] = field(default_factory=list)


def _page_filters(filters: Filters, doc_col: Any, page_col: Any) -> list[Any]:
    conds: list[Any] = []
    if filters.status:
        conds.append(Document.status == filters.status)
    if filters.document_id:
        conds.append(Document.id == filters.document_id)
    lc = filters.logical_conditions()
    if lc:
        conds.append(
            exists().where(
                and_(
                    LogicalDocument.document_id == doc_col,
                    page_col >= LogicalDocument.start_page,
                    page_col <= LogicalDocument.end_page,
                    *lc,
                )
            )
        )
    return conds


def keyword_hits(session: Session, q: str, filters: Filters, limit: int) -> list[Hit]:
    ts = func.websearch_to_tsquery(_EN, q)
    vec = func.to_tsvector(_EN, Page.text)
    rank = func.ts_rank_cd(vec, ts)
    top = (
        select(
            Page.id,
            Page.document_id,
            Page.page_number,
            rank.label("score"),
            Document.original_filename,
        )
        .join(Document, Document.id == Page.document_id)
        .where(vec.op("@@")(ts), *_page_filters(filters, Page.document_id, Page.page_number))
        .order_by(desc(rank), Page.id)
        .limit(limit)
    ).subquery()
    stmt = (
        select(
            top.c.document_id,
            top.c.original_filename,
            top.c.page_number,
            top.c.score,
            func.ts_headline(_EN, Page.text, ts, literal(HIGHLIGHT)).label("snippet"),
        )
        .join(Page, Page.id == top.c.id)
        .order_by(desc(top.c.score))
    )
    return [
        Hit(
            r.document_id,
            r.original_filename,
            r.page_number,
            float(r.score),
            r.snippet or "",
            sources=["keyword"],
        )
        for r in session.execute(stmt)
    ]


def semantic_hits(session: Session, embedder: Embedder, q: str, filters: Filters, limit: int) -> list[Hit]:
    qvec = embedder.embed([q])[0]
    dist = PageEmbedding.embedding.cosine_distance(qvec)
    stmt = (
        select(
            PageEmbedding.document_id,
            Document.original_filename,
            PageEmbedding.page_number,
            PageEmbedding.content,
            dist.label("dist"),
        )
        .join(Document, Document.id == PageEmbedding.document_id)
        .where(*_page_filters(filters, PageEmbedding.document_id, PageEmbedding.page_number))
        .order_by(dist)
        .limit(limit * 3)
    )
    seen: set[tuple[uuid.UUID, int]] = set()
    hits: list[Hit] = []
    for r in session.execute(stmt):
        key = (r.document_id, r.page_number)
        if key in seen:
            continue
        seen.add(key)
        score = 1.0 - float(r.dist)
        if score <= 0:
            continue
        hits.append(
            Hit(
                r.document_id,
                r.original_filename,
                r.page_number,
                score,
                r.content[:300],
                sources=["semantic"],
            )
        )
        if len(hits) >= limit:
            break
    return hits


def _fuse(lists: list[list[Hit]], k: int = 60) -> list[Hit]:
    """Reciprocal rank fusion: robust way to merge rankings that have incomparable scores."""
    merged: dict[tuple[uuid.UUID, int], Hit] = {}
    for hits in lists:
        for rank, h in enumerate(hits, start=1):
            key = (h.document_id, h.page_number)
            if key not in merged:
                merged[key] = Hit(h.document_id, h.filename, h.page_number, 0.0, h.snippet, sources=[])
            m = merged[key]
            m.score += 1.0 / (k + rank)
            m.sources.extend(s for s in h.sources if s not in m.sources)
            if "keyword" in h.sources:
                m.snippet = h.snippet  # keyword snippets carry the highlighting
    return sorted(merged.values(), key=lambda h: h.score, reverse=True)


def _attach_logical(session: Session, hits: list[Hit]) -> None:
    if not hits:
        return
    docs = {h.document_id for h in hits}
    rows = session.scalars(select(LogicalDocument).where(LogicalDocument.document_id.in_(docs)))
    by_doc: dict[uuid.UUID, list[LogicalDocument]] = {}
    for r in rows:
        by_doc.setdefault(r.document_id, []).append(r)
    for h in hits:
        for lg in by_doc.get(h.document_id, []):
            if lg.start_page <= h.page_number <= lg.end_page:
                h.logical = {
                    "id": lg.id,
                    "doc_type": lg.doc_type,
                    "invoice_number": lg.invoice_number,
                    "supplier_name": lg.supplier_name,
                    "total_amount": lg.total_amount,
                    "currency": lg.currency,
                    "needs_review": lg.needs_review,
                }
                break


def search_pages(
    session: Session, embedder: Embedder, q: str, mode: str, filters: Filters, limit: int = 20
) -> list[Hit]:
    if mode == "keyword":
        hits = keyword_hits(session, q, filters, limit)
    elif mode == "semantic":
        hits = semantic_hits(session, embedder, q, filters, limit)
    else:
        hits = _fuse(
            [
                keyword_hits(session, q, filters, 50),
                semantic_hits(session, embedder, q, filters, 50),
            ]
        )[:limit]
    _attach_logical(session, hits)
    return hits


SORTABLE = {
    "created_at": LogicalDocument.created_at,
    "invoice_date": LogicalDocument.invoice_date,
    "total_amount": LogicalDocument.total_amount,
    "supplier_name": LogicalDocument.supplier_name,
    "invoice_number": LogicalDocument.invoice_number,
}


def list_invoices(
    session: Session,
    filters: Filters,
    *,
    sort: str = "created_at",
    descending: bool = True,
    offset: int = 0,
    limit: int = 25,
) -> tuple[int, list[tuple[LogicalDocument, str, str]]]:
    conds = [*filters.logical_conditions()]
    if filters.status:
        conds.append(Document.status == filters.status)
    if filters.document_id:
        conds.append(Document.id == filters.document_id)
    if not filters.doc_type:
        conds.append(LogicalDocument.doc_type.in_(("invoice", "receipt")))
    base = (
        select(LogicalDocument, Document.original_filename, Document.status)
        .join(Document, Document.id == LogicalDocument.document_id)
        .where(*conds)
    )
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    col = SORTABLE.get(sort, LogicalDocument.created_at)
    order = desc(col) if descending else col
    rows = session.execute(base.order_by(order.nulls_last(), LogicalDocument.id).offset(offset).limit(limit)).all()
    return total, [(r[0], r[1], r[2]) for r in rows]
