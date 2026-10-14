"""Request and response models published through OpenAPI."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ExtractorName = Literal["rules", "llm_ocr", "llm_vision"]
DocumentStatus = Literal[
    "queued", "preprocessing", "ocr", "classifying", "extracting", "validating",
    "auto_approved", "needs_review", "rejected", "reviewed", "exported", "failed",
]  # fmt: skip


class DocumentSummary(BaseModel):
    id: str
    original_name: str
    mime: str
    size: int
    status: DocumentStatus
    doc_type: str | None
    decision: str | None
    engine: str
    vendor_name: str | None
    issue_date: str | None
    total: float | None
    error: str | None
    is_sample: bool
    archive_path: str | None
    created_at: datetime
    events_url: str
    thumbnail_url: str | None = None


class PageOut(BaseModel):
    number: int
    url: str
    width: int
    height: int
    preprocess: list[str] = Field(default_factory=list)


class DocumentDetail(DocumentSummary):
    result: dict[str, Any] | None
    final_data: dict[str, Any] | None
    data: dict[str, Any] | None = Field(description="Reviewed values when present, otherwise the extraction")
    pages: list[PageOut]
    original_url: str
    reviews: int


class UploadRejected(BaseModel):
    name: str
    reason: str


class UploadResponse(BaseModel):
    documents: list[DocumentSummary]
    rejected: list[UploadRejected]


class DocumentList(BaseModel):
    items: list[DocumentSummary]
    total: int
    counts: dict[str, int]


class LineItemIn(BaseModel):
    description: str | None = None
    qty: float | None = None
    unit_price: float | None = None
    amount: float | None = None


class ReviewValues(BaseModel):
    vendor_name: str | None = None
    vendor_tax_id: str | None = None
    document_number: str | None = None
    issue_date: str | None = None
    due_date: str | None = None
    currency: str | None = "IDR"
    subtotal: float | None = None
    discount: float | None = None
    tax_amount: float | None = None
    total: float | None = None
    payment_method: str | None = None
    line_items: list[LineItemIn] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    data: ReviewValues
    doc_type: Literal["receipt", "invoice", "other"] | None = None


class ReviewResponse(BaseModel):
    document: DocumentDetail
    validation: list[dict[str, Any]]
    changed_fields: list[str]


class ReprocessRequest(BaseModel):
    engine: ExtractorName = "rules"


class ExportRequest(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=500)
    format: Literal["xlsx", "csv", "json"] = "xlsx"
    include_unreviewed: bool = Field(
        default=False, description="Include documents still waiting for review (marked as such in the file)"
    )


class ExportResponse(BaseModel):
    id: str
    filename: str
    format: str
    count: int
    skipped: list[UploadRejected]
    download_url: str


class ArchiveRequest(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=500)
    name_pattern: str = "{tanggal}_{vendor}_{nomor}_{total}"
    folder_pattern: str = "Arsip/{tahun}/{bulan}/{jenis}"
    apply: bool = Field(default=False, description="Save the paths on the documents and build the ZIP")


class ArchiveItem(BaseModel):
    document_id: str
    original_name: str
    path: str


class ArchiveResponse(BaseModel):
    items: list[ArchiveItem]
    zip_url: str | None = None


class SampleOut(BaseModel):
    name: str
    title: str
    doc_type: str
    description: str
    thumbnail_url: str


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    storage: bool
    queue: bool
    queue_mode: str
    models: dict[str, bool]
    llm_configured: bool
    llm_model: str | None = None
    version: str
