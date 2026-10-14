"""Field confidence: signals -> P(field is correct), calibrated (PRD 8.5).

Signals per field: the extractor's own prior, whether the value is grounded in
the OCR text and how confidently OCR read it, the validation rules that touch
the field, agreement with a second extraction method, and the classifier's
confidence. A logistic regression learns how much each signal is worth;
isotonic or Platt calibration makes the output usable as a probability, so a
threshold can be chosen for a target accuracy.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from pipeline.extract.grounding import ground_value
from pipeline.interfaces import OCRDocument
from pipeline.schema import (
    AMOUNT_FIELDS,
    DATE_FIELDS,
    HEADER_FIELDS,
    REQUIRED_FIELDS,
    Extraction,
    ValidationFinding,
)

CONF_FIELDS = [*HEADER_FIELDS, "line_items"]
RULE_FIELDS = {
    "sum_items_equals_subtotal": ["line_items", "subtotal", "total"],
    "subtotal_plus_tax_equals_total": ["subtotal", "discount", "tax_amount", "total"],
    "line_qty_times_price": ["line_items"],
    "issue_date_valid": ["issue_date"],
    "due_date_after_issue": ["due_date"],
    "total_positive": ["total"],
    "vendor_tax_id_format": ["vendor_tax_id"],
    "tax_rate_matches_config": ["tax_amount"],
}
FEATURE_NAMES = [
    "prior", "present", "required", "grounded", "ground_ocr_conf", "rule_pass", "rule_fail", "rule_count",
    "agree", "disagree", "classifier_conf", "injection", "page_ocr_conf",
    *[f"field={f}" for f in CONF_FIELDS],
]  # fmt: skip


def _kind(field: str) -> str:
    if field in AMOUNT_FIELDS:
        return "amount"
    if field in DATE_FIELDS:
        return "date"
    return "text"


def _same(field: str, a: Any, b: Any) -> bool:
    from pipeline.normalize import text_key

    if a is None or b is None:
        return a is None and b is None
    if field in AMOUNT_FIELDS:
        return abs(float(a) - float(b)) < 0.005
    return text_key(str(a)) == text_key(str(b))


def _items_signature(ex: Extraction) -> list[float]:
    return sorted(round(li.amount, 2) for li in ex.line_items if li.amount is not None)


def field_features(
    ex: Extraction,
    findings: list[ValidationFinding],
    ocr: OCRDocument | None,
    classifier_conf: float,
    secondary: Extraction | None = None,
    injection: bool = False,
) -> dict[str, list[float]]:
    """One feature vector per field in :data:`CONF_FIELDS`."""
    page_conf = float(np.mean([w.conf for w in ocr.words])) if ocr and ocr.words else 0.0
    status: dict[str, list[str]] = {f: [] for f in CONF_FIELDS}
    for fd in findings:
        for f in RULE_FIELDS.get(fd.rule, []):
            if fd.status != "skipped":
                status[f].append(fd.status)
    out: dict[str, list[float]] = {}
    for f in CONF_FIELDS:
        if f == "line_items":
            confs = [li.confidence or 0.0 for li in ex.line_items]
            prior = float(np.mean(confs)) if confs else 0.0
            present = bool(ex.line_items)
            grounded, gconf = (1.0, prior) if present else (0.0, 0.0)
            other = _items_signature(secondary) if secondary is not None else None
            agree = float(other is not None and other == _items_signature(ex))
            disagree = float(other is not None and other != _items_signature(ex))
        else:
            fv = ex.field(f)
            prior = fv.confidence or 0.0
            present = fv.present
            if present and f not in ("currency", "payment_method"):
                g = ground_value(ocr, _kind(f), fv.value, fv.raw)
                grounded, gconf = float(g.found), float(g.ocr_conf or 0.0)
            else:
                grounded, gconf = (1.0, prior) if present else (0.0, 0.0)
            if secondary is not None:
                same = _same(f, fv.value, secondary.field(f).value)
                agree, disagree = float(same), float(not same)
            else:
                agree = disagree = 0.0
        st = status[f]
        vec = [
            prior, float(present), float(f in REQUIRED_FIELDS or f == "line_items"), grounded, gconf,
            float(st.count("pass")), float(st.count("fail") + st.count("warning")), float(len(st)),
            agree, disagree, classifier_conf, float(injection), page_conf,
            *[1.0 if f == g else 0.0 for g in CONF_FIELDS],
        ]  # fmt: skip
        out[f] = vec
    return out


@dataclass
class ConfidenceModel:
    estimator: Any
    method: str  # "isotonic" | "sigmoid" | "none"

    @classmethod
    def fit(cls, x: np.ndarray, y: np.ndarray, method: str = "isotonic") -> ConfidenceModel:
        from sklearn.calibration import CalibratedClassifierCV
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler

        base = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
        if method == "none":
            est = base.fit(x, y)
        else:
            est = CalibratedClassifierCV(base, method=method, cv=5).fit(x, y)
        return cls(est, method)

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(self.estimator.predict_proba(np.atleast_2d(x))[:, 1])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"estimator": self.estimator, "method": self.method, "features": FEATURE_NAMES}, path)

    @classmethod
    def load(cls, path: Path) -> ConfidenceModel:
        obj = joblib.load(path)
        if obj.get("features") != FEATURE_NAMES:
            raise ValueError("confidence model was trained with a different feature set; retrain it")
        return cls(obj["estimator"], obj["method"])


class HeuristicConfidence:
    """Used before a model is trained: the extractor prior, discounted by failed rules and ungrounded values."""

    method = "heuristic"

    def predict(self, x: np.ndarray) -> np.ndarray:
        x = np.atleast_2d(x)
        prior, present, grounded, rule_fail, disagree = x[:, 0], x[:, 1], x[:, 3], x[:, 6], x[:, 9]
        conf = prior * np.where(grounded > 0, 1.0, 0.6) * np.where(rule_fail > 0, 0.5, 1.0)
        conf = conf * np.where(disagree > 0, 0.6, 1.0)
        return np.where(present > 0, conf, 0.5)
