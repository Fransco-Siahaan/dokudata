from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

import filetype
import pymupdf
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.db.models import Document, Review, new_id
from api.db.session import audit, get_db, session_scope
from api.jobs import enqueue_document
from api.schemas.api import (
    DocumentDetail,
    DocumentList,
    ExtractorName,
    ReprocessRequest,
    ReviewRequest,
    ReviewResponse,
    UploadRejected,
    UploadResponse,
)
from api.security import client_ip, rate_limiter, require_owner, verify_signature
from api.services.documents import detail, effective_values, get_owned, summary
from api.settings import get_settings
from api.storage import get_storage
from pipeline.normalize import normalize_vendor, parse_date
from pipeline.schema import Extraction
from pipeline.validate import validate

router = APIRouter(prefix="/documents", tags=["documents"])
ALLOWED = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}
TERMINAL = {"auto_approved", "needs_review", "rejected", "reviewed", "exported", "failed"}
LLM_ENGINES = {"llm_ocr", "llm_vision"}

Owner = Annotated[str, Depends(require_owner)]
DB = Annotated[Session, Depends(get_db)]


def sniff(data: bytes) -> str | None:
    """MIME type from the file's magic bytes; the client-declared type and extension are ignored."""
    kind = filetype.guess(data)
    return kind.mime if kind and kind.mime in ALLOWED else None


def check_pdf(data: bytes, max_pages: int) -> str | None:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return "PDF rusak atau tidak dapat dibuka"
    if doc.needs_pass:
        return "PDF terkunci kata sandi"
    if doc.page_count > max_pages:
        return f"PDF memiliki {doc.page_count} halaman (maksimal {max_pages})"
    return None


LLM_NOT_CONFIGURED = (
    "Metode B/C belum aktif di server ini: isi ANTHROPIC_API_KEY di berkas .env (atau jalankan "
    "`ant auth login`), lalu mulai ulang API."
)


def require_llm() -> None:
    s = get_settings()
    if not s.allow_llm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Metode B/C dinonaktifkan di server ini")
    if not s.llm_configured:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, LLM_NOT_CONFIGURED)


def _llm_quota_ok(db: Session, owner: str) -> bool:
    since = datetime.now(UTC) - timedelta(days=1)
    n = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.owner == owner, Document.engine.in_(LLM_ENGINES), Document.created_at >= since)
    )
    return (n or 0) < get_settings().llm_documents_per_day


def create_document(
    db: Session, owner: str, name: str, data: bytes, mime: str, engine: str, is_sample: bool = False
) -> Document:
    doc = Document(
        id=new_id("doc"),
        owner=owner,
        original_name=name[:255],
        mime=mime,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_key="",
        engine=engine,
        is_sample=is_sample,
    )
    doc.storage_key = f"{owner}/{doc.id}/original.{ALLOWED[mime]}"
    get_storage().put(doc.storage_key, data, mime)
    db.add(doc)
    audit(db, owner, "upload", "document", doc.id, {"name": doc.original_name, "engine": engine})
    return doc


@router.post(
    "", response_model=UploadResponse, status_code=status.HTTP_201_CREATED, summary="Upload documents"
)
async def upload(
    request: Request,
    owner: Owner,
    db: DB,
    files: Annotated[list[UploadFile], File(description="JPG, PNG or PDF, max 10 MB each")],
    engine: Annotated[ExtractorName | None, Form()] = None,
) -> UploadResponse:
    s = get_settings()
    engine = engine or s.default_extractor
    if engine in LLM_ENGINES:
        require_llm()
    if len(files) > s.max_files_per_request:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Maksimal {s.max_files_per_request} berkas per unggahan"
        )
    rate_limiter.hit(f"upload:{client_ip(request)}", s.uploads_per_hour_per_ip, 3600, cost=len(files))
    today = datetime.now(UTC) - timedelta(days=1)
    used = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.owner == owner, Document.created_at >= today)
    )
    if (used or 0) + len(files) > s.documents_per_day_per_session:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Kuota harian dokumen tercapai")
    if engine in LLM_ENGINES and not _llm_quota_ok(db, owner):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Kuota harian mesin LLM tercapai; gunakan mesin aturan"
        )

    created: list[Document] = []
    rejected: list[UploadRejected] = []
    for f in files:
        name = f.filename or "dokumen"
        data = await f.read(s.max_upload_bytes + 1)
        if len(data) > s.max_upload_bytes:
            rejected.append(UploadRejected(name=name, reason=f"Ukuran melebihi {s.max_upload_mb} MB"))
            continue
        if not data:
            rejected.append(UploadRejected(name=name, reason="Berkas kosong"))
            continue
        mime = sniff(data)
        if mime is None:
            rejected.append(
                UploadRejected(name=name, reason="Tipe berkas tidak didukung (hanya JPG, PNG, PDF)")
            )
            continue
        if mime == "application/pdf" and (problem := check_pdf(data, s.max_pdf_pages)):
            rejected.append(UploadRejected(name=name, reason=problem))
            continue
        created.append(create_document(db, owner, name, data, mime, engine))
    db.commit()
    for doc in created:
        enqueue_document(doc.id)
    return UploadResponse(documents=[summary(d) for d in created], rejected=rejected)


@router.get("", response_model=DocumentList, summary="List documents")
def list_documents(
    owner: Owner,
    db: DB,
    status_: Annotated[list[str] | None, Query(alias="status")] = None,
    doc_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = Query(default=None, max_length=100),
    ids: Annotated[list[str] | None, Query()] = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
) -> DocumentList:
    stmt = select(Document).where(Document.owner == owner)
    if status_:
        stmt = stmt.where(Document.status.in_(status_))
    if doc_type:
        stmt = stmt.where(Document.doc_type == doc_type)
    if date_from:
        stmt = stmt.where(Document.issue_date >= date_from.isoformat())
    if date_to:
        stmt = stmt.where(Document.issue_date <= date_to.isoformat())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Document.vendor_name.ilike(like) | Document.original_name.ilike(like))
    if ids:
        stmt = stmt.where(Document.id.in_(ids))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    docs = db.scalars(stmt.order_by(Document.created_at.desc()).limit(limit).offset(offset)).all()
    counts = dict(
        db.execute(
            select(Document.status, func.count()).where(Document.owner == owner).group_by(Document.status)
        ).all()
    )
    return DocumentList(
        items=[summary(d) for d in docs], total=total, counts={k: int(v) for k, v in counts.items()}
    )


@router.get("/{doc_id}", response_model=DocumentDetail, summary="Document detail with results and validation")
def get_document(doc_id: str, owner: Owner, db: DB) -> DocumentDetail:
    return detail(get_owned(db, owner, doc_id))


@router.get("/{doc_id}/events", summary="Server-sent status events (signed URL from the document summary)")
async def events(doc_id: str, request: Request) -> StreamingResponse:
    verify_signature(request)

    async def stream() -> AsyncIterator[str]:
        last = None
        for _ in range(1200):  # at most ~10 minutes
            if await request.is_disconnected():
                return
            with session_scope() as db:
                doc = db.get(Document, doc_id)
                state = (doc.status, doc.decision, doc.error) if doc else ("deleted", None, None)
            if state != last:
                last = state
                payload = {"status": state[0], "decision": state[1], "error": state[2]}
                yield f"event: status\ndata: {json.dumps(payload)}\n\n"
            if state[0] in TERMINAL or state[0] == "deleted":
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def _clean_review(values: dict[str, Any]) -> dict[str, Any]:
    v = dict(values)
    v["vendor_name"] = normalize_vendor(v.get("vendor_name"))
    for f in ("issue_date", "due_date"):
        if v.get(f):
            parsed = parse_date(v[f])
            if parsed is None:
                raise HTTPException(422, f"Format tanggal {f} tidak dikenali")
            v[f] = parsed
    if v.get("discount") is not None:
        v["discount"] = abs(v["discount"])
    v["line_items"] = [
        li for li in v.get("line_items") or [] if li.get("description") or li.get("amount") is not None
    ]
    return v


@router.patch("/{doc_id}/review", response_model=ReviewResponse, summary="Save the reviewer's corrections")
def review(doc_id: str, body: ReviewRequest, owner: Owner, db: DB) -> ReviewResponse:
    doc = get_owned(db, owner, doc_id)
    if doc.status not in TERMINAL or doc.status == "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Dokumen belum selesai diproses")
    before = effective_values(doc) or {}
    after = _clean_review(body.data.model_dump())
    changed = [k for k in after if before.get(k) != after.get(k)]
    findings = validate(Extraction.from_values(after, source="human"))
    blocking = [f for f in findings if f.status == "fail"]
    if blocking and (body.doc_type or doc.doc_type) != "other":
        # Reviewed data is exported as validated, so hard failures must be fixed first.
        raise HTTPException(
            422,
            {"message": "Data belum valid", "validation": [f.model_dump() for f in blocking]},
        )
    db.add(Review(document_id=doc.id, reviewer=owner[:12], data_final=after,
                  diff={k: {"before": before.get(k), "after": after.get(k)} for k in changed}))  # fmt: skip
    doc.final_data = after
    if body.doc_type:
        doc.doc_type = body.doc_type
    doc.status = "reviewed"
    doc.vendor_name, doc.issue_date, doc.total = (
        after.get("vendor_name"),
        after.get("issue_date"),
        after.get("total"),
    )
    audit(db, owner, "review", "document", doc.id, {"changed": changed})
    db.commit()
    db.refresh(doc)
    return ReviewResponse(
        document=detail(doc), validation=[f.model_dump() for f in findings], changed_fields=changed
    )


@router.post(
    "/{doc_id}/reprocess", response_model=DocumentDetail, summary="Run the pipeline again with another engine"
)
def reprocess(doc_id: str, body: ReprocessRequest, owner: Owner, db: DB) -> DocumentDetail:
    doc = get_owned(db, owner, doc_id)
    if body.engine in LLM_ENGINES:
        require_llm()
        if not _llm_quota_ok(db, owner):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Kuota harian mesin LLM tercapai")
    doc.engine = body.engine
    doc.status, doc.error, doc.final_data = "queued", None, None
    audit(db, owner, "reprocess", "document", doc.id, {"engine": body.engine})
    db.commit()
    enqueue_document(doc.id)
    db.refresh(doc)
    return detail(doc)


@router.delete(
    "/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and everything derived from it",
)
def delete_document(doc_id: str, owner: Owner, db: DB) -> None:
    doc = get_owned(db, owner, doc_id)
    get_storage().delete_prefix(f"{owner}/{doc.id}")
    audit(db, owner, "delete", "document", doc.id)
    db.delete(doc)
    db.commit()
