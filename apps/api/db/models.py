"""Database entities (PRD 13.1)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def new_id(prefix: str) -> str:
    """Random, non-sequential ids so documents cannot be enumerated."""
    return f"{prefix}_{secrets.token_urlsafe(12)}"


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("doc"))
    owner: Mapped[str] = mapped_column(String(64), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    phash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    data_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    storage_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    doc_type: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    decision: Mapped[str | None] = mapped_column(String(24), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    engine: Mapped[str] = mapped_column(String(32), default="rules")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    final_data: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_date: Mapped[str | None] = mapped_column(String(10), nullable=True, index=True)
    total: Mapped[float | None] = mapped_column(Float, nullable=True)
    archive_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_sample: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pages: Mapped[list[Page]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Page.number"
    )
    extractions: Mapped[list[ExtractionRow]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    reviews: Mapped[list[Review]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Page(Base):
    __tablename__ = "pages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pg"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    image_key: Mapped[str] = mapped_column(String(255))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    preprocess: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)

    document: Mapped[Document] = relationship(back_populates="pages")
    ocr_results: Mapped[list[OCRResultRow]] = relationship(
        back_populates="page", cascade="all, delete-orphan"
    )


class OCRResultRow(Base):
    __tablename__ = "ocr_results"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ocr"))
    page_id: Mapped[str] = mapped_column(ForeignKey("pages.id", ondelete="CASCADE"), index=True)
    engine: Mapped[str] = mapped_column(String(32))
    words: Mapped[list[Any]] = mapped_column(JSONType)
    elapsed_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cer: Mapped[float | None] = mapped_column(Float, nullable=True)

    page: Mapped[Page] = relationship(back_populates="ocr_results")


class ExtractionRow(Base):
    __tablename__ = "extractions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ext"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    engine: Mapped[str] = mapped_column(String(32))
    data: Mapped[dict[str, Any]] = mapped_column(JSONType)
    field_conf: Mapped[dict[str, Any]] = mapped_column(JSONType)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    document: Mapped[Document] = relationship(back_populates="extractions")
    validations: Mapped[list[ValidationRow]] = relationship(
        back_populates="extraction", cascade="all, delete-orphan"
    )


class ValidationRow(Base):
    __tablename__ = "validations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("val"))
    extraction_id: Mapped[str] = mapped_column(ForeignKey("extractions.id", ondelete="CASCADE"), index=True)
    rule: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    detail: Mapped[str] = mapped_column(Text, default="")

    extraction: Mapped[ExtractionRow] = relationship(back_populates="validations")


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("rev"))
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    reviewer: Mapped[str] = mapped_column(String(64))
    data_final: Mapped[dict[str, Any]] = mapped_column(JSONType)
    diff: Mapped[dict[str, Any]] = mapped_column(JSONType)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    document: Mapped[Document] = relationship(back_populates="reviews")


class Export(Base):
    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("exp"))
    owner: Mapped[str] = mapped_column(String(64), index=True)
    document_ids: Mapped[list[str]] = mapped_column(JSONType)
    format: Mapped[str] = mapped_column(String(8))
    storage_key: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("eval"))
    dataset_version: Mapped[str] = mapped_column(String(64))
    engine_config: Mapped[dict[str, Any]] = mapped_column(JSONType)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(32))
    entity: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
