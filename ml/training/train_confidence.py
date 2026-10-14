"""Train and calibrate the field-confidence model, then choose decision thresholds (PRD 8.5, 6.3).

    python -m ml.training.train_confidence

* Fit on the train split. The classifier signal comes from out-of-fold
  predictions, so the confidence model does not learn from an over-confident
  classifier that has already seen those documents.
* Compare no calibration, Platt (sigmoid) and isotonic on the validation split
  and keep the best by log loss.
* Choose the field threshold on validation: the lowest threshold whose
  auto-approved documents reach the target accuracy (all fields right), which
  maximises automation at that accuracy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from ml.common import records
from ml.evaluation.harness import conf_rows, doc_correct, llm_extract, ocr_for, rules_extract
from ml.evaluation.metrics import expected_calibration_error
from pipeline.classify import SklearnTextClassifier
from pipeline.confidence import CONF_FIELDS, ConfidenceModel, decide
from pipeline.config import MODELS_DIR, rules_config

REPORT = Path("reports/training/confidence.json")
LLM_ENGINES = ["llm_ocr", "llm_vision"]


def oof_classifier_conf(texts: list[str], labels: list[str]) -> list[tuple[str, float]]:
    proba = cross_val_predict(
        SklearnTextClassifier.build(), texts, labels, cv=StratifiedKFold(5, shuffle=True, random_state=0),
        method="predict_proba",
    )  # fmt: skip
    classes = sorted(set(labels))
    return [(classes[int(np.argmax(p))], float(np.max(p))) for p in proba]


def build_rows(
    split: str, cls: list[tuple[str, float]]
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    xs, ys, docs = [], [], []
    for rec, (label, conf) in zip(records(split), cls, strict=True):
        ocr = ocr_for(rec, "primary")
        gt = rec["ground_truth"]
        rules = rules_extract(ocr) if ocr else None
        candidates: list[tuple[str, Any, Any, Any]] = [("rules", rules, None, None)] if rules else []
        for eng in LLM_ENGINES:
            got = llm_extract(eng, rec, "primary", ocr)
            if got:
                candidates.append((eng, got[0], rules, got[1]))
        for engine, ex, secondary, meta in candidates:
            if rec["doc_type"] == "other":
                docs.append(
                    {"rec": rec, "engine": engine, "ex": ex, "cls": (label, conf), "findings": [], "x": None}
                )
                continue
            x, y, findings = conf_rows(ex, gt, ocr, conf, secondary, meta)
            xs.append(x)
            ys.append(y)
            docs.append(
                {"rec": rec, "engine": engine, "ex": ex, "cls": (label, conf), "findings": findings, "x": x}
            )
    return np.vstack(xs), np.concatenate(ys), docs


def choose_thresholds(model: Any, docs: list[dict[str, Any]], target: float) -> dict[str, Any]:
    grid_f = [round(t, 3) for t in np.concatenate([np.arange(0.5, 0.95, 0.05), np.arange(0.95, 1.0, 0.005)])]
    grid_c = [0.6, 0.7, 0.8, 0.9, 0.95]
    prepared = []
    for d in docs:
        conf = dict(zip(CONF_FIELDS, model.predict(d["x"]), strict=True)) if d["x"] is not None else {}
        correct = d["rec"]["doc_type"] != "other" and d["cls"][0] == d["rec"]["doc_type"] and doc_correct(
            d["ex"].values(), d["rec"]["ground_truth"])[1]  # fmt: skip
        prepared.append((d, conf, correct))
    curve, best = [], None
    for tc in grid_c:
        for tf in grid_f:
            approved = correct_n = 0
            for d, conf, correct in prepared:
                label, cconf = d["cls"]
                if not conf:
                    continue
                dec = decide(label, cconf, d["ex"], d["findings"], conf, tf, tc)
                if dec.decision == "auto_approved":
                    approved += 1
                    correct_n += int(correct)
            n_docs = sum(1 for _, c, _ in prepared if c)
            cov = approved / max(1, n_docs)
            acc = correct_n / approved if approved else 1.0
            curve.append(
                {
                    "classifier_threshold": tc,
                    "field_threshold": tf,
                    "coverage": round(cov, 4),
                    "accuracy": round(acc, 4),
                }
            )
            if approved >= 5 and acc >= target and (best is None or cov > best["coverage"]):
                best = curve[-1]
    if best is None:  # target unreachable on validation: be conservative
        best = {"classifier_threshold": 0.95, "field_threshold": 0.995, "coverage": 0.0, "accuracy": None}
    return {"chosen": best, "curve": curve}


def main() -> None:
    target = float(rules_config()["decision"]["target_accuracy"])
    train = list(records("train"))
    texts = []
    for rec in train:
        ocr = ocr_for(rec, "primary")
        if ocr is None:
            raise SystemExit("OCR cache missing; run ml.evaluation.ocr_cache first")
        texts.append(ocr.text)
    cls_train = oof_classifier_conf(texts, [r["doc_type"] for r in train])
    clf = SklearnTextClassifier.load(MODELS_DIR / "classifier_tfidf.joblib")
    val = list(records("val"))
    val_texts = [ocr_for(r, "primary").text for r in val]  # type: ignore[union-attr]
    cls_val = [(r.label, r.confidence) for r in clf.predict_many(val_texts)]

    x_tr, y_tr, _ = build_rows("train", cls_train)
    x_va, y_va, val_docs = build_rows("val", cls_val)
    print(f"confidence rows: train={len(y_tr)} (positive {y_tr.mean():.1%}), val={len(y_va)}")

    results: dict[str, Any] = {"train_rows": int(len(y_tr)), "val_rows": int(len(y_va))}
    best_name, best_model, best_ll = "", None, float("inf")
    for method in ("none", "sigmoid", "isotonic"):
        m = ConfidenceModel.fit(x_tr, y_tr, method)
        p = np.clip(m.predict(x_va), 1e-6, 1 - 1e-6)
        ll = log_loss(y_va, p)
        results[method] = {"log_loss": round(ll, 4), "brier": round(brier_score_loss(y_va, p), 4),
                           "ece": expected_calibration_error(p, y_va)["ece"]}  # fmt: skip
        print(f"{method:9s} val log-loss={ll:.4f} ECE={results[method]['ece']:.4f}")
        m.save(MODELS_DIR / f"confidence_{method}.joblib")  # kept for the E5 comparison
        if ll < best_ll:
            best_name, best_model, best_ll = method, m, ll
    assert best_model is not None
    best_model.save(MODELS_DIR / "confidence.joblib")
    results["chosen"] = best_name

    th = choose_thresholds(best_model, val_docs, target)
    chosen = th["chosen"]
    results["thresholds"] = chosen
    results["threshold_curve"] = th["curve"]
    (MODELS_DIR / "decision.toml").write_text(
        "# Chosen on the validation split by ml.training.train_confidence; do not edit by hand.\n"
        f"field_threshold = {chosen['field_threshold']}\nclassifier_threshold = {chosen['classifier_threshold']}\n"
        f"target_accuracy = {target}\nvalidation_coverage = {chosen['coverage']}\n",
        encoding="utf-8",
    )
    print(f"chosen calibration={best_name}; thresholds={chosen}")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
