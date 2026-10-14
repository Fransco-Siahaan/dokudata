"""Evaluation metrics (PRD 11.1)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from pipeline.normalize import text_key
from pipeline.schema import AMOUNT_FIELDS, DATE_FIELDS, HEADER_FIELDS

EVAL_FIELDS = [f for f in HEADER_FIELDS if f != "currency"]
TEXT_SIMILARITY_FIELDS = ["vendor_name", "document_number"]


def values_equal(field: str, pred: Any, gt: Any) -> bool:
    if pred is None or gt is None:
        return pred is None and gt is None
    if field in AMOUNT_FIELDS:
        try:
            return abs(float(pred) - float(gt)) < 0.005
        except (TypeError, ValueError):
            return False
    if field in DATE_FIELDS:
        return str(pred) == str(gt)
    if field == "vendor_tax_id":
        return text_key(str(pred)) == text_key(str(gt))
    return text_key(str(pred)) == text_key(str(gt))


def edit_similarity(pred: Any, gt: Any) -> float:
    """Normalised edit similarity in [0, 1] on comparison keys."""
    a, b = text_key(str(pred or "")), text_key(str(gt or ""))
    if not a and not b:
        return 1.0
    return float(Levenshtein.normalized_similarity(a, b))


@dataclass(slots=True)
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, other: Counts) -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def as_dict(self) -> dict[str, float]:
        return {"tp": self.tp, "fp": self.fp, "fn": self.fn, "precision": round(self.precision, 4),
                "recall": round(self.recall, 4), "f1": round(self.f1, 4)}  # fmt: skip


def field_counts(field: str, pred: Any, gt: Any) -> Counts:
    """A wrong prediction is both a false positive and a false negative (SROIE-style)."""
    c = Counts()
    has_p, has_g = pred is not None and pred != "", gt is not None and gt != ""
    if has_p and has_g:
        if values_equal(field, pred, gt):
            c.tp = 1
        else:
            c.fp = c.fn = 1
    elif has_p:
        c.fp = 1
    elif has_g:
        c.fn = 1
    return c


def match_line_items(
    pred: list[dict[str, Any]], gt: list[dict[str, Any]], threshold: float = 0.8
) -> tuple[Counts, list[tuple[int, int]]]:
    """Row-level matching: same amount and description similarity >= threshold (greedy, best first)."""
    pairs = []
    for i, p in enumerate(pred):
        for j, g in enumerate(gt):
            if p.get("amount") is None or g.get("amount") is None:
                continue
            if abs(float(p["amount"]) - float(g["amount"])) >= 0.005:
                continue
            sim = fuzz.ratio(text_key(p.get("description")), text_key(g.get("description"))) / 100
            if sim >= threshold:
                pairs.append((sim, i, j))
    pairs.sort(reverse=True)
    used_p, used_g, matched = set(), set(), []
    for _, i, j in pairs:
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        matched.append((i, j))
    c = Counts(tp=len(matched), fp=len(pred) - len(matched), fn=len(gt) - len(matched))
    return c, matched


def cer(reference: str, hypothesis: str) -> float:
    ref = " ".join(reference.split())
    hyp = " ".join(hypothesis.split())
    return Levenshtein.distance(ref, hyp) / max(1, len(ref))


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = reference.split(), hypothesis.split()
    return Levenshtein.distance(ref, hyp) / max(1, len(ref))


def classification_report(
    y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str]
) -> dict[str, Any]:
    idx = {lab: i for i, lab in enumerate(labels)}
    cm = np.zeros((len(labels), len(labels)), dtype=int)
    for t, p in zip(y_true, y_pred, strict=True):
        cm[idx[t], idx[p]] += 1
    per_class = {}
    f1s = []
    for lab, i in idx.items():
        tp = cm[i, i]
        fp = cm[:, i].sum() - tp
        fn = cm[i, :].sum() - tp
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        f1s.append(f1)
        per_class[lab] = {
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "support": int(cm[i].sum()),
        }
    return {
        "accuracy": round(float(np.trace(cm) / max(1, cm.sum())), 4),
        "macro_f1": round(float(np.mean(f1s)), 4),
        "per_class": per_class,
        "labels": list(labels),
        "confusion_matrix": cm.tolist(),
    }


def expected_calibration_error(
    conf: Sequence[float], correct: Sequence[bool], n_bins: int = 10
) -> dict[str, Any]:
    c = np.asarray(conf, dtype=float)
    y = np.asarray(correct, dtype=float)
    edges = np.linspace(0, 1, n_bins + 1)
    bins = []
    ece = 0.0
    for lo, hi in itertools_pairwise(edges):
        mask = (c >= lo) & (c < hi) if hi < 1 else (c >= lo) & (c <= hi)
        n = int(mask.sum())
        if n == 0:
            bins.append(
                {"lo": round(lo, 2), "hi": round(hi, 2), "n": 0, "confidence": None, "accuracy": None}
            )
            continue
        acc, cf = float(y[mask].mean()), float(c[mask].mean())
        ece += n / max(1, len(c)) * abs(acc - cf)
        bins.append(
            {
                "lo": round(lo, 2),
                "hi": round(hi, 2),
                "n": n,
                "confidence": round(cf, 4),
                "accuracy": round(acc, 4),
            }
        )
    return {"ece": round(float(ece), 4), "bins": bins, "n": len(c)}


def itertools_pairwise(a: np.ndarray) -> list[tuple[float, float]]:
    return [(float(a[i]), float(a[i + 1])) for i in range(len(a) - 1)]


def coverage_accuracy_curve(conf: Sequence[float], correct: Sequence[bool]) -> list[dict[str, float]]:
    """Accuracy of the items kept when only those with confidence >= t are auto-approved."""
    c = np.asarray(conf, dtype=float)
    y = np.asarray(correct, dtype=bool)
    order = np.argsort(-c)
    cs, ys = c[order], y[order]
    out = []
    cum = np.cumsum(ys)
    n = len(c)
    for k in range(1, n + 1):
        if k < n and cs[k] == cs[k - 1]:
            continue  # only evaluate at distinct thresholds
        out.append({"threshold": round(float(cs[k - 1]), 4), "coverage": round(k / n, 4),
                    "accuracy": round(float(cum[k - 1] / k), 4)})  # fmt: skip
    return out


def bootstrap_ci(
    per_doc: Sequence[Any],
    stat: Callable[[Sequence[Any]], float],
    n_boot: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n = len(per_doc)
    if n == 0:
        return (float("nan"), float("nan"))
    vals = []
    for _ in range(n_boot):
        sample = [per_doc[i] for i in rng.integers(0, n, n)]
        vals.append(stat(sample))
    return float(np.quantile(vals, alpha / 2)), float(np.quantile(vals, 1 - alpha / 2))
