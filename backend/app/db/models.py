"""ORM models. See docs/DATABASE_SCHEMA.md for the explanation of each table."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    literal_column,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")
EMBEDDING_DIM = 384


def _now() -> Any:
    return func.now()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="viewer")  # admin|reviewer|viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    original_filename: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(10))  # pdf|image|xlsx|xls|csv
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="uploaded", index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now(), onupdate=_now())

    pages: Mapped[list[Page]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )
    logical_documents: Mapped[list[LogicalDocument]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)  # 1-based; for spreadsheets: sheet number
    label: Mapped[str | None] = mapped_column(String(255))  # sheet name
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|done|failed
    method: Mapped[str | None] = mapped_column(String(12))  # text_layer|ocr|table|empty
    text: Mapped[str] = mapped_column(Text, default="")
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    width: Mapped[float | None] = mapped_column(Float)
    height: Mapped[float | None] = mapped_column(Float)
    layout: Mapped[Any | None] = mapped_column(JSONType)  # words with boxes, or sheet rows
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now(), onupdate=_now())

    document: Mapped[Document] = relationship(back_populates="pages")


# Full-text search index (must match the expression used by the search service).
Index(
    "ix_pages_fts",
    func.to_tsvector(literal_column("'english'"), Page.__table__.c.text),
    postgresql_using="gin",
)


class LogicalDocument(Base):
    """One invoice/receipt/other found inside an uploaded file (a file may hold many)."""

    __tablename__ = "logical_documents"
    __table_args__ = (
        UniqueConstraint("document_id", "position"),
        Index("ix_logical_supplier_invoice", "supplier_name", "invoice_number"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    doc_type: Mapped[str] = mapped_column(String(12))  # invoice|receipt|other
    start_page: Mapped[int] = mapped_column(Integer)
    end_page: Mapped[int] = mapped_column(Integer)
    classification_score: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(12), default="rules")  # rules|spreadsheet
    sheet_ref: Mapped[Any | None] = mapped_column(JSONType)
    extraction_status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|done|failed
    error: Mapped[str | None] = mapped_column(Text)

    # Denormalised "effective" values for filtering/sorting (refreshed after extraction/correction).
    invoice_number: Mapped[str | None] = mapped_column(String(200), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(300))
    customer_name: Mapped[str | None] = mapped_column(String(300))
    invoice_date: Mapped[date | None] = mapped_column(Date, index=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    currency: Mapped[str | None] = mapped_column(String(8))
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    review_status: Mapped[str] = mapped_column(String(10), default="pending")  # pending|approved
    validation_status: Mapped[str] = mapped_column(String(10), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())

    document: Mapped[Document] = relationship(back_populates="logical_documents")


class Extraction(Base):
    __tablename__ = "extractions"
    __table_args__ = (UniqueConstraint("logical_document_id", "version"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    logical_document_id: Mapped[int] = mapped_column(ForeignKey("logical_documents.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    raw_json: Mapped[Any | None] = mapped_column(JSONType)
    overall_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    usage: Mapped[Any | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    __table_args__ = (UniqueConstraint("extraction_id", "name"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    extraction_id: Mapped[int] = mapped_column(ForeignKey("extractions.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(40))
    value: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[Any | None] = mapped_column(JSONType)  # [x0,y0,x1,y1] in page units, or {sheet,cell}
    source: Mapped[str] = mapped_column(String(10), default="extracted")  # extracted|inferred
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    grounded: Mapped[bool] = mapped_column(Boolean, default=True)


class LineItem(Base):
    __tablename__ = "line_items"
    __table_args__ = (UniqueConstraint("extraction_id", "position"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    extraction_id: Mapped[int] = mapped_column(ForeignKey("extractions.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    page: Mapped[int | None] = mapped_column(Integer)
    raw_text: Mapped[str | None] = mapped_column(Text)
    bbox: Mapped[Any | None] = mapped_column(JSONType)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)


class Correction(Base):
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    logical_document_id: Mapped[int] = mapped_column(ForeignKey("logical_documents.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(12))  # field|line_item
    field_name: Mapped[str] = mapped_column(String(40))
    line_item_position: Mapped[int | None] = mapped_column(Integer)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    logical_document_id: Mapped[int] = mapped_column(ForeignKey("logical_documents.id", ondelete="CASCADE"), index=True)
    rule_code: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(10))  # error|warning|info
    message: Mapped[str] = mapped_column(Text)
    field: Mapped[str | None] = mapped_column(String(40))
    expected: Mapped[str | None] = mapped_column(Text)
    actual: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class ProcessingEvent(Base):
    __tablename__ = "processing_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    logical_document_id: Mapped[int | None] = mapped_column(BigInteger)
    stage: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(12))  # started|completed|failed|info|warning
    message: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[Any | None] = mapped_column(JSONType)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now(), index=True)


class Comparison(Base):
    __tablename__ = "comparisons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    left_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    right_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    summary: Mapped[Any | None] = mapped_column(JSONType)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now())


class ComparisonItem(Base):
    __tablename__ = "comparison_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    comparison_id: Mapped[int] = mapped_column(ForeignKey("comparisons.id", ondelete="CASCADE"), index=True)
    pair_index: Mapped[int] = mapped_column(Integer)
    left_logical_id: Mapped[int | None] = mapped_column(BigInteger)
    right_logical_id: Mapped[int | None] = mapped_column(BigInteger)
    field: Mapped[str] = mapped_column(String(40))
    left_value: Mapped[str | None] = mapped_column(Text)
    right_value: Mapped[str | None] = mapped_column(Text)
    left_source: Mapped[Any | None] = mapped_column(JSONType)
    right_source: Mapped[Any | None] = mapped_column(JSONType)
    verdict: Mapped[str] = mapped_column(String(20))
    rule: Mapped[str | None] = mapped_column(Text)


class PageEmbedding(Base):
    __tablename__ = "page_embeddings"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_id: Mapped[int] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM))

    __table_args__ = (
        Index(
            "ix_page_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(50), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(30))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[Any | None] = mapped_column(JSONType)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_now(), index=True)
