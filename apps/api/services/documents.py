"""Shared document helpers for the routers."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from api.db.models import Document
from api.schemas.api import DocumentDetail, DocumentSummary, PageOut
from api.security import signed_url
from pipeline.schema import Extraction

API = "/api/v1"


def get_owned(db: Session, owner: str, doc_id: str) -> Document:
    doc = db.get(Document, doc_id)
    # Same 404 for "missing" and "not yours": no information about other sessions' ids.
    if doc is None or doc.owner != owner:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dokumen tidak ditemukan")
    return doc


def file_url(key: str) -> str:
    return signed_url(f"{API}/files/{key}")


def summary(doc: Document) -> DocumentSummary:
    thumb = file_url(doc.pages[0].image_key) if doc.pages else None
    return DocumentSummary(
        id=doc.id,
        original_name=doc.original_name,
        mime=doc.mime,
        size=doc.size,
        status=doc.status,  # type: ignore[arg-type]
        doc_type=doc.doc_type,
        decision=doc.decision,
        engine=doc.engine,
        vendor_name=doc.vendor_name,
        issue_date=doc.issue_date,
        total=doc.total,
        error=doc.error,
        is_sample=doc.is_sample,
        archive_path=doc.archive_path,
        created_at=doc.created_at,
        events_url=signed_url(f"{API}/documents/{doc.id}/events", ttl=3600),
        thumbnail_url=thumb,
    )


def effective_values(doc: Document) -> dict[str, Any] | None:
    """What an export uses: the reviewer's values when present, else the extraction."""
    if doc.final_data:
        return doc.final_data
    if doc.result:
        return Extraction.model_validate(doc.result["extraction"]).values()
    return None


def detail(doc: Document) -> DocumentDetail:
    s = summary(doc)
    return DocumentDetail(
        **s.model_dump(),
        result=doc.result,
        final_data=doc.final_data,
        data=effective_values(doc),
        pages=[
            PageOut(
                number=p.number,
                url=file_url(p.image_key),
                width=p.width,
                height=p.height,
                preprocess=p.preprocess or [],
            )
            for p in doc.pages
        ],  # fmt: skip
        original_url=file_url(doc.storage_key),
        reviews=len(doc.reviews),
    )
