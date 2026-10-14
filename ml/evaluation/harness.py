"""Glue between cached data and the pipeline components, shared by training and evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ml.evaluation.metrics import EVAL_FIELDS, match_line_items, values_equal
from ml.evaluation.ocr_cache import load_cached
from pipeline.confidence import CONF_FIELDS, field_features
from pipeline.extract.llm import LLMOutput, to_extraction
from pipeline.extract.rules import RulesExtractor
from pipeline.interfaces import ExtractionInput, OCRDocument
from pipeline.safety import find_injection
from pipeline.schema import REQUIRED_FIELDS, Extraction, ValidationFinding
from pipeline.validate import validate

LLM_CACHE = Path("data/cache/llm")
_rules = RulesExtractor()


def variant_of(rec: dict[str, Any], variant: str) -> str:
    return rec["primary"] if variant == "primary" else variant


def ocr_for(
    rec: dict[str, Any], variant: str, engine: str = "rapidocr", preprocess: bool = True
) -> OCRDocument | None:
    return load_cached(engine, preprocess, rec["split"], rec["doc_id"], variant_of(rec, variant))


def rules_extract(ocr: OCRDocument) -> Extraction:
    return _rules.extract(ExtractionInput([], ocr, "receipt")).extraction


def llm_cache_path(engine: str, rec: dict[str, Any], variant: str) -> Path:
    return LLM_CACHE / engine / rec["split"] / f"{rec['doc_id']}_{variant_of(rec, variant)}.json"


def llm_extract(
    engine: str, rec: dict[str, Any], variant: str, ocr: OCRDocument | None
) -> tuple[Extraction, dict[str, Any]] | None:
    p = llm_cache_path(engine, rec, variant)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    if data.get("error"):
        return Extraction(), data
    out = LLMOutput.model_validate(data["output"])
    ex, grounded = to_extraction(out, engine, ocr)
    meta = {**data.get("meta", {}), "grounded": grounded, "suspicious_instructions": out.suspicious_instructions,
            "llm_document_type": out.document_type}  # fmt: skip
    return ex, meta


def field_label(field: str, pred: dict[str, Any], gt: dict[str, Any]) -> bool:
    if field == "line_items":
        c, _ = match_line_items(pred.get("line_items") or [], gt.get("line_items") or [])
        return c.fp == 0 and c.fn == 0
    if field == "currency":
        return (pred.get("currency") or "IDR") == (gt.get("currency") or "IDR")
    return values_equal(field, pred.get(field), gt.get(field))


def doc_correct(pred: dict[str, Any], gt: dict[str, Any]) -> tuple[bool, bool]:
    """(all required fields right, every header field and every line item right)."""
    required = all(values_equal(f, pred.get(f), gt.get(f)) for f in REQUIRED_FIELDS if f != "currency")
    exact = all(values_equal(f, pred.get(f), gt.get(f)) for f in EVAL_FIELDS) and field_label(
        "line_items", pred, gt
    )
    return required, exact


def findings_for(
    ex: Extraction, meta: dict[str, Any] | None, ocr: OCRDocument | None
) -> list[ValidationFinding]:
    from datetime import date

    findings = validate(ex, today=date(2026, 10, 11))
    grounded = (meta or {}).get("grounded") or {}
    ungrounded = [f for f, ok in grounded.items() if not ok]
    if ungrounded and ocr is not None:
        findings.append(
            ValidationFinding(rule="values_present_in_document", status="warning", fields=ungrounded)
        )
    return findings


def conf_rows(
    ex: Extraction,
    gt: dict[str, Any],
    ocr: OCRDocument | None,
    classifier_conf: float,
    secondary: Extraction | None = None,
    meta: dict[str, Any] | None = None,
) -> tuple[np.ndarray, np.ndarray, list[ValidationFinding]]:
    findings = findings_for(ex, meta, ocr)
    injection = bool(find_injection(ocr.text if ocr else "")) or bool(
        (meta or {}).get("suspicious_instructions")
    )
    feats = field_features(ex, findings, ocr, classifier_conf, secondary, injection)
    pred = ex.values()
    x = np.array([feats[f] for f in CONF_FIELDS], dtype=float)
    y = np.array([field_label(f, pred, gt) for f in CONF_FIELDS], dtype=int)
    return x, y, findings
