"""Files, evaluation summary, demo samples and health."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from api import __version__
from api.db.session import get_db
from api.jobs import enqueue_document, queue_ping
from api.routers.documents import create_document, require_llm, sniff
from api.schemas.api import DocumentSummary, HealthOut, SampleOut
from api.security import client_ip, rate_limiter, require_owner, signed_url, verify_signature
from api.services.documents import API, summary
from api.settings import get_settings
from api.storage import get_storage
from pipeline.config import MODELS_DIR

router = APIRouter()
Owner = Annotated[str, Depends(require_owner)]
DB = Annotated[Session, Depends(get_db)]
CONTENT_TYPES = {"jpg": "image/jpeg", "png": "image/png", "pdf": "application/pdf"}


@router.get("/files/{key:path}", tags=["files"], summary="Signed access to page images and originals")
def get_file(key: str, request: Request) -> Response:
    verify_signature(request)
    try:
        data = get_storage().get(key)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Berkas tidak ditemukan") from exc
    except Exception as exc:  # S3 NoSuchKey and friends
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Berkas tidak ditemukan") from exc
    ext = key.rsplit(".", 1)[-1].lower()
    return Response(data, media_type=CONTENT_TYPES.get(ext, "application/octet-stream"),
                    headers={"Cache-Control": "private, max-age=3600"})  # fmt: skip


@router.get(
    "/evaluation/summary", tags=["evaluation"], summary="Latest evaluation metrics for the Evaluation page"
)
def evaluation_summary() -> dict[str, Any]:
    path = get_settings().reports_dir / "latest" / "summary.json"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Belum ada hasil evaluasi; jalankan `make evaluate`")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/evaluation/assets/{name}", tags=["evaluation"], summary="Charts and error-analysis crops")
def evaluation_asset(name: str) -> Response:
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,120}\.(png|jpg)", name) or ".." in name:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aset tidak ditemukan")
    latest = get_settings().reports_dir / "latest"
    for path in (latest / "errors" / name, latest / name):
        if path.is_file():
            media = "image/png" if name.endswith(".png") else "image/jpeg"
            return Response(
                path.read_bytes(), media_type=media, headers={"Cache-Control": "public, max-age=3600"}
            )
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Aset tidak ditemukan")


def _samples() -> list[dict[str, Any]]:
    index = get_settings().samples_dir / "samples.json"
    return json.loads(index.read_text(encoding="utf-8")) if index.exists() else []


@router.get(
    "/demo/samples", response_model=list[SampleOut], tags=["demo"], summary="Synthetic sample documents"
)
def list_samples() -> list[SampleOut]:
    return [
        SampleOut(
            name=s["name"],
            title=s["title"],
            doc_type=s["doc_type"],
            description=s["description"],
            thumbnail_url=signed_url(f"{API}/demo/samples/{s['name']}/thumbnail", ttl=86400),
        )  # fmt: skip
        for s in _samples()
    ]


def _sample_file(name: str) -> tuple[dict[str, Any], Path]:
    sample = next((s for s in _samples() if s["name"] == name), None)
    if sample is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contoh tidak ditemukan")
    return sample, get_settings().samples_dir / sample["file"]


@router.get("/demo/samples/{name}/thumbnail", tags=["demo"], include_in_schema=False)
def sample_thumbnail(name: str, request: Request) -> Response:
    verify_signature(request)
    sample, _ = _sample_file(name)
    thumb = get_settings().samples_dir / sample["thumbnail"]
    return Response(
        thumb.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"}
    )


@router.post("/demo/samples/{name}", response_model=DocumentSummary, status_code=201, tags=["demo"],
             summary="Process a sample document in this session")  # fmt: skip
def run_sample(name: str, request: Request, owner: Owner, db: DB, engine: str = "rules") -> DocumentSummary:
    if engine not in ("rules", "llm_ocr", "llm_vision"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Mesin tidak dikenal")
    if engine != "rules":
        require_llm()
    rate_limiter.hit(f"demo:{client_ip(request)}", 60, 3600)
    sample, path = _sample_file(name)
    data = path.read_bytes()
    mime = sniff(data)
    if mime is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Berkas contoh rusak")
    doc = create_document(db, owner, sample["file"], data, mime, engine, is_sample=True)
    db.commit()
    enqueue_document(doc.id)
    return summary(doc)


@router.get("/health", response_model=HealthOut, tags=["health"])
def health(db: DB) -> HealthOut:
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    storage_ok = get_storage().ping()
    q_ok = queue_ping()
    models = {name: (MODELS_DIR / f).exists() for name, f in
              [("classifier_tfidf", "classifier_tfidf.joblib"), ("confidence", "confidence.joblib")]}  # fmt: skip
    s = get_settings()
    llm = s.allow_llm and s.llm_configured
    ok = db_ok and storage_ok and q_ok
    return HealthOut(status="ok" if ok else "degraded", database=db_ok, storage=storage_ok, queue=q_ok,
                     queue_mode=get_settings().queue_mode, models=models, llm_configured=llm, llm_model=s.llm_model if llm else None, version=__version__)  # fmt: skip
