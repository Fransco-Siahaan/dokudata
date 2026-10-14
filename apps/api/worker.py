"""Document processing job: runs the pipeline and persists every intermediate result.

Run standalone workers with ``rq worker documents`` (Docker) or let the API use
its inline thread pool (development).
"""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from api.db.models import Document, ExtractionRow, OCRResultRow, Page, ValidationRow
from api.db.session import session_scope
from api.settings import get_settings
from api.storage import get_storage
from pipeline.duplicates import amount_anomaly, data_key, find_duplicates, perceptual_hash
from pipeline.llm import ClaudeClient, LLMClient, LLMUnavailableError
from pipeline.preprocess import DocumentLoadError, encode_jpeg
from pipeline.runner import Pipeline, PipelineConfig
from pipeline.schema import ValidationFinding

log = logging.getLogger("dokudata.worker")
_pipelines: dict[tuple[str, str, str], Pipeline] = {}
_lock = threading.Lock()


def llm_client() -> LLMClient:
    """Claude client for methods B and C, configured from settings (tests replace this)."""
    s = get_settings()
    return ClaudeClient(model=s.llm_model, effort=s.llm_effort, api_key=s.anthropic_api_key)


def get_pipeline(extractor: str) -> Pipeline:
    s = get_settings()
    key = (extractor, s.ocr_engine, s.classifier)
    with _lock:
        if key not in _pipelines:
            client = llm_client() if extractor in ("llm_ocr", "llm_vision") else None
            _pipelines[key] = Pipeline(
                PipelineConfig(ocr_engine=s.ocr_engine, extractor=extractor, classifier=s.classifier),
                llm_client=client,
            )
        return _pipelines[key]


def _set_status(doc_id: str, status: str) -> None:
    with session_scope() as db:
        doc = db.get(Document, doc_id)
        if doc is not None:
            doc.status = status


def process_document(document_id: str) -> str:
    storage = get_storage()
    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            return "missing"
        data = storage.get(doc.storage_key)
        mime, engine, owner = doc.mime, doc.engine, doc.owner
        doc.status, doc.error = "preprocessing", None

    try:
        pipeline = get_pipeline(engine)
        out = pipeline.run(data, mime, on_stage=lambda st: _set_status(document_id, st))
    except DocumentLoadError as exc:
        _fail(document_id, str(exc))
        return "failed"
    except LLMUnavailableError as exc:
        _fail(document_id, f"Mesin LLM tidak tersedia: {exc}")
        return "failed"
    except Exception as exc:
        log.exception("processing failed for %s", document_id)
        _fail(document_id, f"Kesalahan saat memproses: {type(exc).__name__}")
        raise

    result = out.result
    values = result.extraction.values()
    phash = perceptual_hash(out.pages[0]) if out.pages else None
    key = data_key(values)

    with session_scope() as db:
        doc = db.get(Document, document_id)
        if doc is None:
            return "missing"
        for page in list(doc.pages):
            db.delete(page)
        db.flush()
        for i, img in enumerate(out.pages):
            img_key = f"{owner}/{doc.id}/page-{i + 1}.jpg"
            storage.put(img_key, encode_jpeg(img, 88), "image/jpeg")
            h, w = img.shape[:2]
            info = out.preprocess_info[i].steps if i < len(out.preprocess_info) else []
            page = Page(
                document_id=doc.id, number=i + 1, image_key=img_key, width=w, height=h, preprocess=info
            )
            db.add(page)
            db.flush()
            if out.ocr is not None and i < len(out.ocr.pages):
                op = out.ocr.pages[i]
                words = [
                    {"t": wd.text, "b": [round(c, 1) for c in wd.bbox], "c": round(wd.conf, 3)}
                    for wd in op.words
                ]
                db.add(OCRResultRow(page_id=page.id, engine=op.engine, words=words, elapsed_ms=op.elapsed_ms))

        # Duplicates and anomalies are checked against the same session's earlier documents.
        others = db.execute(
            select(Document.id, Document.sha256, Document.phash, Document.data_key).where(
                Document.owner == owner, Document.id != doc.id, Document.status != "failed"
            )
        ).all()
        dups = find_duplicates(doc.id, doc.sha256, phash, key, [(r[0], r[1], r[2], r[3]) for r in others])
        if dups:
            detail = "; ".join(f"{d.detail} dengan {d.other_id}" for d in dups)
            result.validation.append(
                ValidationFinding(rule="duplicate_document", status="warning", detail=detail)
            )
            result.flags.append(f"Kemungkinan duplikat: {detail}")
        if values.get("vendor_name") and values.get("total") is not None:
            history = db.execute(
                select(Document.total).where(
                    Document.owner == owner, Document.vendor_name == values["vendor_name"], Document.id != doc.id,
                    Document.total.is_not(None),
                )
            ).scalars().all()  # fmt: skip
            note = amount_anomaly(float(values["total"]), [float(t) for t in history if t is not None])
            if note:
                result.validation.append(
                    ValidationFinding(rule="amount_anomaly", status="warning", detail=note)
                )
                result.flags.append(note)
        decision = result.decision
        if decision == "auto_approved" and (dups or result.flags):
            decision = "needs_review"
            result.decision = "needs_review"
            result.decision_reasons.extend(result.flags)

        ext = ExtractionRow(
            document_id=doc.id,
            engine=out.primary.engine,
            data=values,
            field_conf={k: v for k, v in _field_conf(result.model_dump()).items()},
            latency_ms=sum(result.timings_ms.values()),
            cost=result.cost_usd,
        )
        db.add(ext)
        db.flush()
        for fd in result.validation:
            db.add(ValidationRow(extraction_id=ext.id, rule=fd.rule, status=fd.status, detail=fd.detail))

        doc.result = result.model_dump(mode="json")
        doc.final_data = None
        doc.phash, doc.data_key = phash, key
        doc.doc_type = result.document_type.value
        doc.decision = decision
        doc.status = {"auto_approved": "auto_approved", "rejected": "rejected"}.get(decision, "needs_review")
        doc.vendor_name = values.get("vendor_name")
        doc.issue_date = values.get("issue_date")
        doc.total = values.get("total")
        doc.processed_at = datetime.now(UTC)
        return doc.status


def _field_conf(result: dict[str, Any]) -> dict[str, float | None]:
    ex = result["extraction"]
    out: dict[str, float | None] = {k: v.get("confidence") for k, v in ex.items() if isinstance(v, dict)}
    items = ex.get("line_items") or []
    out["line_items"] = min((li.get("confidence") or 0.0 for li in items), default=None)
    return out


def _fail(doc_id: str, reason: str) -> None:
    with session_scope() as db:
        doc = db.get(Document, doc_id)
        if doc is not None:
            doc.status, doc.error = "failed", reason
