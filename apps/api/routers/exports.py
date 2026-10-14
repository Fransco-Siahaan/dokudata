from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.db.models import Document, Export, new_id
from api.db.session import audit, get_db
from api.schemas.api import (
    ArchiveItem,
    ArchiveRequest,
    ArchiveResponse,
    ExportRequest,
    ExportResponse,
    UploadRejected,
)
from api.security import require_owner, signed_url, verify_signature
from api.services.documents import API, effective_values
from api.storage import get_storage
from pipeline.archive import archive_path, dedupe_paths
from pipeline.export import EXPORTERS, MIME, ExportRow

router = APIRouter(tags=["exports"])
Owner = Annotated[str, Depends(require_owner)]
DB = Annotated[Session, Depends(get_db)]
VALIDATED = {"auto_approved", "reviewed", "exported"}


def _owned_docs(db: Session, owner: str, ids: list[str]) -> list[Document]:
    docs = db.scalars(select(Document).where(Document.owner == owner, Document.id.in_(ids))).all()
    by_id = {d.id: d for d in docs}
    return [by_id[i] for i in ids if i in by_id]


@router.post(
    "/exports",
    response_model=ExportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Export to Excel, CSV or JSON",
)
def create_export(body: ExportRequest, owner: Owner, db: DB) -> ExportResponse:
    docs = _owned_docs(db, owner, body.document_ids)
    rows: list[ExportRow] = []
    skipped: list[UploadRejected] = []
    for d in docs:
        values = effective_values(d)
        if values is None or d.status == "failed":
            skipped.append(UploadRejected(name=d.original_name, reason="Belum ada hasil ekstraksi"))
        elif d.status not in VALIDATED and not body.include_unreviewed:
            # Money data only leaves the system as validated after rules pass or a human reviewed it.
            skipped.append(UploadRejected(name=d.original_name, reason="Belum ditinjau"))
        else:
            rows.append(
                ExportRow(
                    d.id, d.doc_type or "other", d.status, values, d.archive_path or "", d.original_name
                )
            )
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, {"message": "Tidak ada dokumen yang dapat diekspor",
                                                           "skipped": [s.model_dump() for s in skipped]})  # fmt: skip
    data = EXPORTERS[body.format](rows)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    exp = Export(id=new_id("exp"), owner=owner, document_ids=[r.document_id for r in rows], format=body.format, storage_key="",
                 filename=f"dokudata-{stamp}.{body.format}")  # fmt: skip
    exp.storage_key = f"{owner}/exports/{exp.id}.{body.format}"
    get_storage().put(exp.storage_key, data, MIME[body.format])
    db.add(exp)
    for d in docs:
        if d.id in exp.document_ids and d.status in VALIDATED:
            d.status = "exported"
    audit(db, owner, "export", "export", exp.id, {"format": body.format, "count": len(rows)})
    db.commit()
    return ExportResponse(id=exp.id, filename=exp.filename, format=body.format, count=len(rows), skipped=skipped,
                          download_url=signed_url(f"{API}/exports/{exp.id}/download"))  # fmt: skip


@router.get("/exports/{export_id}/download", summary="Download an export (signed URL)")
def download_export(export_id: str, request: Request, db: DB) -> Response:
    verify_signature(request)
    exp = db.get(Export, export_id)
    if exp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ekspor tidak ditemukan")
    return Response(get_storage().get(exp.storage_key), media_type=MIME[exp.format],
                    headers={"Content-Disposition": f'attachment; filename="{exp.filename}"'})  # fmt: skip


@router.post(
    "/archive/organize", response_model=ArchiveResponse, summary="Preview or apply archive names and folders"
)
def organize(body: ArchiveRequest, owner: Owner, db: DB) -> ArchiveResponse:
    docs = _owned_docs(db, owner, body.document_ids)
    try:
        raw = [
            archive_path(
                effective_values(d) or {},
                d.doc_type or "other",
                d.storage_key.rsplit(".", 1)[-1],
                body.name_pattern,
                body.folder_pattern,
            )  # fmt: skip
            for d in docs
        ]
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    paths = dedupe_paths(raw)
    items = [
        ArchiveItem(document_id=d.id, original_name=d.original_name, path=p)
        for d, p in zip(docs, paths, strict=True)
    ]
    if not body.apply:
        return ArchiveResponse(items=items)
    buf = io.BytesIO()
    storage = get_storage()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for d, p in zip(docs, paths, strict=True):
            zf.writestr(p, storage.get(d.storage_key))
            d.archive_path = p
    exp = Export(id=new_id("exp"), owner=owner, document_ids=[d.id for d in docs], format="zip", storage_key="",
                 filename=f"arsip-{datetime.now(UTC):%Y%m%d-%H%M%S}.zip")  # fmt: skip
    exp.storage_key = f"{owner}/exports/{exp.id}.zip"
    storage.put(exp.storage_key, buf.getvalue(), MIME["zip"])
    db.add(exp)
    audit(db, owner, "archive", "export", exp.id, {"count": len(docs)})
    db.commit()
    return ArchiveResponse(items=items, zip_url=signed_url(f"{API}/exports/{exp.id}/download"))
