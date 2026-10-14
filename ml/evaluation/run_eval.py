"""Evaluate everything on the frozen test splits with one command (PRD 11, FR-53).

    python -m ml.evaluation.run_eval            # local engines only (free)
    python -m ml.evaluation.run_eval --system-n 20

LLM methods are included automatically when their cached answers exist
(``python -m ml.evaluation.llm_runs --yes``). Outputs:

* reports/runs/<run_id>/summary.json  and  reports/latest/summary.json (served to the Evaluation page)
* reports/latest/errors/*.jpg          (error-analysis crops)
* docs/evaluation-report.md            (generated report)
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ml.common import DATA, check_frozen, records
from ml.evaluation.harness import (
    conf_rows,
    doc_correct,
    field_label,
    llm_extract,
    ocr_for,
    rules_extract,
)
from ml.evaluation.metrics import (
    EVAL_FIELDS,
    Counts,
    bootstrap_ci,
    cer,
    classification_report,
    coverage_accuracy_curve,
    edit_similarity,
    expected_calibration_error,
    field_counts,
    match_line_items,
    values_equal,
    wer,
)
from ml.evaluation.ocr_cache import CACHE
from ml.evaluation.report import write_model_card, write_report
from pipeline.classify import EmbeddingClassifier, KeywordClassifier, SklearnTextClassifier
from pipeline.confidence import CONF_FIELDS, ConfidenceModel, HeuristicConfidence, decide
from pipeline.config import MODELS_DIR, decision_config, rules_config
from pipeline.extract.grounding import ground_value
from pipeline.extract.rules import RulesExtractor
from pipeline.interfaces import ExtractionInput
from pipeline.preprocess import preprocess
from pipeline.safety import find_injection
from pipeline.schema import AMOUNT_FIELDS, DATE_FIELDS, DOC_TYPES

SPLITS = ["test_seen", "test_unseen"]
VARIANTS = ["clean", "degraded"]
ENGINE_LABELS = {
    "rules": "A · OCR + aturan",
    "llm_ocr": "B · OCR + LLM (Claude)",
    "llm_vision": "C · LLM visi (Claude)",
}
KEY_FIELDS = ["vendor_name", "issue_date", "total"]
TAX_NO_FIELDS = ["tax_amount", "document_number", "vendor_tax_id"]
REPORTS = Path("reports")
ERROR_LABELS = {
    "ocr": "Kesalahan OCR (teks benar tidak terbaca)",
    "wrong_field": "Salah memilih field (mis. subtotal/tunai sebagai total)",
    "format": "Salah format (pemisah ribuan/desimal, urutan tanggal)",
    "missed": "Field tidak terdeteksi oleh aturan",
    "spurious": "Mengisi field yang tidak ada di dokumen",
    "line_items": "Item baris terpotong, tergabung, atau salah angka",
    "hallucination": "Halusinasi LLM (nilai tidak ada di dokumen)",
    "partial": "Teks terpotong atau tergabung (mis. nama vendor dua baris)",
    "other": "Lainnya",
}


def kind(field: str) -> str:
    return "amount" if field in AMOUNT_FIELDS else "date" if field in DATE_FIELDS else "text"


def pct(n: float, d: float) -> float:
    return round(n / d, 4) if d else 0.0


def quantile(values: list[float], q: float) -> float | None:
    return round(float(np.quantile(values, q)), 1) if values else None


# --------------------------------------------------------------------------- E1 / E2


def eval_ocr() -> list[dict[str, Any]]:
    rows = []
    for engine_dir in sorted(p for p in CACHE.iterdir() if p.is_dir()) if CACHE.exists() else []:
        for pp_dir in sorted(engine_dir.iterdir()):
            for split in SPLITS:
                for variant in VARIANTS:
                    cers, wers, times = [], [], []
                    for rec in records(split):
                        f = pp_dir / split / f"{rec['doc_id']}_{variant}.json"
                        if not f.exists():
                            continue
                        data = json.loads(f.read_text(encoding="utf-8"))
                        from ml.evaluation.ocr_cache import from_json

                        hyp = from_json(data).text
                        cers.append(cer(rec["reference_text"], hyp))
                        wers.append(wer(rec["reference_text"], hyp))
                        times.append(sum(p.get("elapsed_ms", 0) for p in data["pages"]))
                    if cers:
                        rows.append({"engine": engine_dir.name, "subset": f"{split}/{variant}", "preprocess": pp_dir.name == "pp",
                                     "n": len(cers), "cer": round(statistics.mean(cers), 4), "wer": round(statistics.mean(wers), 4),
                                     "ms_per_page": round(statistics.mean(times), 1)})  # fmt: skip
    return rows


# --------------------------------------------------------------------------- E3


def eval_classification(
    test_docs: list[tuple[dict[str, Any], str]],
) -> tuple[list[dict[str, Any]], dict[str, list[tuple[str, float]]]]:
    texts = [ocr_for(rec, v).text for rec, v in test_docs]  # type: ignore[union-attr]
    y = [rec["doc_type"] for rec, _ in test_docs]
    preds: dict[str, list[tuple[str, float]]] = {}
    kw = KeywordClassifier()
    preds["Kata kunci (tanpa latih)"] = [(r.label, r.confidence) for r in map(kw.predict, texts)]
    tfidf_path = MODELS_DIR / "classifier_tfidf.joblib"
    if tfidf_path.exists():
        m = SklearnTextClassifier.load(tfidf_path)
        preds["TF-IDF + regresi logistik"] = [(r.label, r.confidence) for r in m.predict_many(texts)]
    emb_path = MODELS_DIR / "classifier_embedding.joblib"
    if emb_path.exists():
        e = EmbeddingClassifier.load(emb_path)
        preds["Embedding multibahasa + regresi logistik"] = [
            (r.label, r.confidence) for r in e.predict_embeddings(e.embed(texts))
        ]
    out = []
    for name, p in preds.items():
        labels = [lab for lab, _ in p]
        out.append({"name": name, "subset": "all", **classification_report(y, labels, DOC_TYPES)})
        for split in SPLITS:
            idx = [i for i, (rec, _) in enumerate(test_docs) if rec["split"] == split]
            out.append({"name": name, "subset": split,
                        **classification_report([y[i] for i in idx], [labels[i] for i in idx], DOC_TYPES)})  # fmt: skip
    return out, preds


# --------------------------------------------------------------------------- E4 / E6


def extract_all(engine: str, docs: list[tuple[dict[str, Any], str]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Per (doc_id, variant): extraction, metadata and timings for one engine."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    extractor = RulesExtractor()
    for rec, variant in docs:
        ocr = ocr_for(rec, variant)
        if engine == "rules":
            t0 = time.perf_counter()
            ex = extractor.extract(ExtractionInput([], ocr, rec["doc_type"])).extraction
            out[(rec["doc_id"], variant)] = {
                "ex": ex,
                "meta": {},
                "latency_ms": (time.perf_counter() - t0) * 1000,
                "cost": 0.0,
            }
        else:
            got = llm_extract(engine, rec, variant, ocr)
            if got is None:
                continue
            ex, meta = got
            out[(rec["doc_id"], variant)] = {"ex": ex, "meta": meta, "latency_ms": meta.get("latency_ms"),
                                             "cost": meta.get("cost_usd", 0.0)}  # fmt: skip
    return out


def score(
    docs: list[tuple[dict[str, Any], str]], results: dict[tuple[str, str], dict[str, Any]]
) -> dict[str, Any]:
    fields = {f: Counts() for f in EVAL_FIELDS}
    items = Counts()
    req = exact = 0
    sims, lat, costs = [], [], []
    per_doc = []
    for rec, variant in docs:
        r = results.get((rec["doc_id"], variant))
        if r is None:
            continue
        pred, gt = r["ex"].values(), rec["ground_truth"]
        doc_fields = {}
        for f in EVAL_FIELDS:
            c = field_counts(f, pred.get(f), gt.get(f))
            fields[f].add(c)
            doc_fields[f] = c
        c, _ = match_line_items(pred["line_items"], gt["line_items"])
        items.add(c)
        a, b = doc_correct(pred, gt)
        req += a
        exact += b
        sims.append(edit_similarity(pred.get("vendor_name"), gt.get("vendor_name")))
        if r["latency_ms"] is not None:
            lat.append(float(r["latency_ms"]))
        costs.append(float(r["cost"] or 0.0))
        per_doc.append(doc_fields)
    n = len(per_doc)
    return {
        "n": n,
        "fields": {f: c.as_dict() for f, c in fields.items()},
        "line_items": items.as_dict(),
        "doc_required": pct(req, n),
        "doc_exact": pct(exact, n),
        "vendor_similarity": round(float(np.mean(sims)), 4) if sims else None,
        "latency_p50_ms": quantile(lat, 0.5),
        "latency_p95_ms": quantile(lat, 0.95),
        "cost_per_doc": round(float(np.mean(costs)), 6) if costs else None,
        "_per_doc": per_doc,
    }


def f1_of(per_doc: list[dict[str, Counts]], fields: list[str]) -> float:
    c = Counts()
    for d in per_doc:
        for f in fields:
            c.add(d[f])
    return c.f1


# --------------------------------------------------------------------------- E5


def eval_confidence(docs, results, cls_conf) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    th = decision_config()
    target = float(rules_config()["decision"]["target_accuracy"])
    models: dict[str, Any] = {"Prior ekstraktor (tanpa model)": None, "Heuristik": HeuristicConfidence()}
    for method, label in (
        ("none", "Regresi logistik"),
        ("sigmoid", "LR + Platt"),
        ("isotonic", "LR + isotonik"),
    ):
        p = MODELS_DIR / f"confidence_{method}.joblib"
        if p.exists():
            models[label] = ConfidenceModel.load(p)
    chosen_path = MODELS_DIR / "confidence.joblib"
    chosen = ConfidenceModel.load(chosen_path) if chosen_path.exists() else HeuristicConfidence()
    xs, ys, prepared = [], [], []
    for (rec, variant), (label, cconf) in zip(docs, cls_conf, strict=True):
        r = results.get((rec["doc_id"], variant))
        if r is None:
            continue
        ocr = ocr_for(rec, variant)
        if rec["doc_type"] == "other":
            prepared.append(((rec, variant), r, (label, cconf), None, [], False))
            continue
        x, y, findings = conf_rows(r["ex"], rec["ground_truth"], ocr, cconf, None, r["meta"])
        xs.append(x)
        ys.append(y)
        correct = label == rec["doc_type"] and doc_correct(r["ex"].values(), rec["ground_truth"])[1]
        prepared.append(((rec, variant), r, (label, cconf), x, findings, correct))
    X, Y = np.vstack(xs), np.concatenate(ys)
    methods = []
    for name, m in models.items():
        p = X[:, 0] if m is None else m.predict(X)
        methods.append({"name": name, **expected_calibration_error(p, Y)})
    # Report the prior, the uncalibrated LR and the deployed calibrated model (<= 3 series in the chart).
    keep = [
        "Prior ekstraktor (tanpa model)",
        "Regresi logistik",
        next((n for n in ("LR + isotonik", "LR + Platt") if n in models), "Heuristik"),
    ]
    methods = [m for name in keep for m in methods if m["name"] == name] + [
        m for m in methods if m["name"] not in keep
    ]

    def decisions(tf: float, tc: float, subset: str | None = None) -> tuple[int, int, int]:
        n_in = n_auto = n_ok = 0
        for (rec, variant), r, (label, cconf), x, findings, correct in prepared:
            if subset and f"{rec['split']}/{variant}" != subset:
                continue
            if rec["doc_type"] != "other":
                n_in += 1
            if x is None:
                # Out-of-scope pages only count when the classifier mistakes them for a receipt/invoice
                # and every gate passes, which the decision below handles as an error.
                if label == "other":
                    continue
                conf = {f: 0.0 for f in CONF_FIELDS}
                findings = []
            else:
                conf = dict(zip(CONF_FIELDS, chosen.predict(x), strict=True))
            dec = decide(label, cconf, r["ex"], findings, conf, tf, tc)
            if dec.decision == "auto_approved":
                n_auto += 1
                n_ok += int(correct)
        return n_in, n_auto, n_ok

    tc = float(th["classifier_threshold"])
    curve = []
    for tf in sorted(
        set([round(t, 3) for t in np.concatenate([np.arange(0.3, 0.95, 0.05), np.arange(0.95, 1.0, 0.0025)])])
    ):
        n_in, n_auto, n_ok = decisions(tf, tc)
        if n_auto:
            curve.append({"threshold": tf, "coverage": pct(n_auto, n_in), "accuracy": pct(n_ok, n_auto)})
    n_in, n_auto, n_ok = decisions(float(th["field_threshold"]), tc)
    by_subset = {}
    for sub in [f"{s}/{v}" for s in SPLITS for v in VARIANTS]:
        a, b, c = decisions(float(th["field_threshold"]), tc, sub)
        by_subset[sub] = {
            "n_docs": a,
            "n_auto": b,
            "automation_rate": pct(b, a),
            "auto_accuracy": pct(c, b) if b else None,
        }
    field_curve = coverage_accuracy_curve(chosen.predict(X), Y)
    return {
        "methods": methods,
        "coverage": [{"name": "Dokumen (aturan keputusan lengkap)", "points": curve}],
        "field_coverage": field_curve[:: max(1, len(field_curve) // 200)],
        "decision": {
            "field_threshold": float(th["field_threshold"]),
            "classifier_threshold": tc,
            "automation_rate": pct(n_auto, n_in),
            "auto_accuracy": pct(n_ok, n_auto) if n_auto else None,
            "n_docs": n_in,
            "n_auto": n_auto,
            "target": target,
            "by_subset": by_subset,
        },  # fmt: skip
    }


# --------------------------------------------------------------------------- errors


def categorize(
    field: str, pred: Any, gt: Any, gt_all: dict[str, Any], ocr, engine: str, meta: dict[str, Any]
) -> str:  # type: ignore[no-untyped-def]
    if gt is not None and pred is None:
        return "missed" if ground_value(ocr, kind(field), gt, str(gt)).found else "ocr"
    if gt is None and pred is not None:
        if engine != "rules" and not (meta.get("grounded") or {}).get(field, True):
            return "hallucination"
        return "spurious"
    if field in AMOUNT_FIELDS:
        others = [v for k, v in gt_all.items() if k in AMOUNT_FIELDS and k != field and v is not None]
        if any(abs(float(pred) - float(o)) < 0.005 for o in others):
            return "wrong_field"
        p, g = str(int(round(float(pred) * 100))).rstrip("0"), str(int(round(float(gt) * 100))).rstrip("0")
        if p == g:
            return "format"
    if field in DATE_FIELDS and isinstance(pred, str) and isinstance(gt, str) and len(pred) == 10:
        if pred[:4] == gt[:4] and pred[5:7] == gt[8:10] and pred[8:10] == gt[5:7]:
            return "format"
    if engine != "rules" and not (meta.get("grounded") or {}).get(field, True):
        return "hallucination"
    if not ground_value(ocr, kind(field), gt, str(gt)).found:
        return "ocr"
    if field in AMOUNT_FIELDS:
        return "wrong_field"
    # Text: a near miss is a truncated/merged value; anything else is another line of the page.
    return "partial" if edit_similarity(pred, gt) >= 0.6 else "wrong_field"


def _item_text(li: dict[str, Any]) -> str:
    amount = li.get("amount")
    return f"{li.get('description')} = {amount:,.0f}" if amount is not None else str(li.get("description"))


def error_analysis(engine: str, docs, results, out_dir: Path) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    cats: Counter[str] = Counter()
    examples_by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec, variant in docs:
        if rec["doc_type"] == "other":
            continue
        r = results.get((rec["doc_id"], variant))
        if r is None:
            continue
        ocr = ocr_for(rec, variant)
        pred, gt = r["ex"].values(), rec["ground_truth"]
        for f in EVAL_FIELDS:
            if values_equal(f, pred.get(f), gt.get(f)):
                continue
            c = categorize(f, pred.get(f), gt.get(f), gt, ocr, engine, r["meta"])
            cats[c] += 1
            examples_by_cat[c].append({"rec": rec, "variant": variant, "field": f, "pred": pred.get(f), "gt": gt.get(f),
                                       "bbox": r["ex"].field(f).bbox, "ocr": ocr})  # fmt: skip
        if not field_label("line_items", pred, gt):
            cats["line_items"] += 1
            _, pairs = match_line_items(pred["line_items"], gt["line_items"])
            mp, mg = {i for i, _ in pairs}, {j for _, j in pairs}
            fmt = _item_text
            wrong_p = [fmt(li) for i, li in enumerate(pred["line_items"]) if i not in mp][:2]
            wrong_g = [fmt(li) for j, li in enumerate(gt["line_items"]) if j not in mg][:2]
            examples_by_cat["line_items"].append({"rec": rec, "variant": variant, "field": "line_items",
                "pred": "; ".join(wrong_p) or "(tidak ada)", "gt": "; ".join(wrong_g) or "(tidak ada)", "bbox": None, "ocr": ocr})  # fmt: skip
    total = sum(cats.values())
    err_dir = out_dir / "errors"
    err_dir.mkdir(parents=True, exist_ok=True)
    examples = []
    rng = np.random.default_rng(0)
    for c, _ in cats.most_common():
        pool = examples_by_cat[c]
        for i in rng.choice(len(pool), size=min(2, len(pool)), replace=False):
            ex = pool[int(i)]
            image = crop_example(ex, err_dir)
            examples.append({"doc_id": ex["rec"]["doc_id"], "subset": f"{ex['rec']['split']}/{ex['variant']}", "field": ex["field"],
                             "pred": "" if ex["pred"] is None else str(ex["pred"]), "gt": "" if ex["gt"] is None else str(ex["gt"]),
                             "category": c, "image": image})  # fmt: skip
    return {
        "engine": engine,
        "total_errors": total,
        "categories": [
            {"category": c, "label": ERROR_LABELS[c], "count": n, "share": pct(n, total)}
            for c, n in cats.most_common()
        ],
        "examples": examples[:12],
    }


def crop_example(ex: dict[str, Any], err_dir: Path) -> str | None:
    rec = ex["rec"]
    img = cv2.imread(str(DATA / rec["split"] / rec["files"][ex["variant"]]))
    if img is None:
        return None
    img, _ = preprocess(img)
    bbox = ex["bbox"]
    if bbox is None and ex["gt"] is not None and ex["field"] != "line_items":
        g = ground_value(ex["ocr"], kind(ex["field"]), ex["gt"], str(ex["gt"]))
        bbox = list(g.bbox) if g.bbox else None
    h, w = img.shape[:2]
    if bbox:
        x0, y0, x1, y1 = (int(v) for v in bbox)
        pad_y = max(40, (y1 - y0) * 3)
        crop = img[max(0, y0 - pad_y) : min(h, y1 + pad_y), 0:w].copy()
        cv2.rectangle(
            crop,
            (x0 - 4, y0 - max(0, y0 - pad_y) - 4),
            (x1 + 4, y1 - max(0, y0 - pad_y) + 4),
            (40, 120, 214),
            3,
        )
    else:
        crop = img[: min(h, int(w * 0.9))]
    scale = min(1.0, 640 / crop.shape[1])
    crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    name = f"{rec['doc_id']}_{ex['variant']}_{ex['field']}.jpg"
    cv2.imwrite(str(err_dir / name), crop, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return name


# --------------------------------------------------------------------------- injection & system


def eval_injection(engines: list[str]) -> dict[str, Any]:
    recs = list(records("injection"))
    detected = forced = auto = 0
    by_engine: dict[str, dict[str, float]] = {}
    tfidf = SklearnTextClassifier.load(MODELS_DIR / "classifier_tfidf.joblib")
    chosen = ConfidenceModel.load(MODELS_DIR / "confidence.joblib")
    th = decision_config()
    n = 0
    for engine in engines:
        ok = flagged = seen = 0
        for rec in recs:
            for variant in VARIANTS:
                ocr = ocr_for(rec, variant)
                if ocr is None:
                    continue
                if engine == "rules":
                    ex, meta = rules_extract(ocr), {}
                else:
                    got = llm_extract(engine, rec, variant, ocr)
                    if got is None:
                        continue
                    ex, meta = got
                seen += 1
                ok += int(values_equal("total", ex.total.value, rec["ground_truth"]["total"]))
                flagged += int(bool(meta.get("suspicious_instructions")))
                if engine == "rules":
                    n += 1
                    hits = find_injection(ocr.text)
                    detected += int(bool(hits))
                    cls = tfidf.predict(ocr.text)
                    x, _, findings = conf_rows(ex, rec["ground_truth"], ocr, cls.confidence, None, meta)
                    conf = dict(zip(CONF_FIELDS, chosen.predict(x), strict=True))
                    flags = ["prompt injection"] if hits else []
                    dec = decide(cls.label, cls.confidence, ex, findings, conf, float(th["field_threshold"]),
                                 float(th["classifier_threshold"]), flags)  # fmt: skip
                    forced += int(dec.decision != "auto_approved")
                    auto += int(dec.decision == "auto_approved")
        if seen:
            by_engine[engine] = {"total_correct_rate": pct(ok, seen), "n": seen}
            if engine != "rules":
                by_engine[engine]["flagged_by_model_rate"] = pct(flagged, seen)
    return {
        "n": n,
        "detected_rate": pct(detected, n),
        "forced_review_rate": pct(forced, n),
        "auto_approved": auto,
        "by_engine": by_engine,
    }


def eval_system(n: int) -> dict[str, Any]:
    """Real end-to-end timings (preprocess + OCR + everything) on a sample of test images."""
    from pipeline.runner import Pipeline, PipelineConfig

    pipe = Pipeline(PipelineConfig())
    sample = []
    for split in SPLITS:
        for rec in records(split):
            if rec["doc_type"] != "other":
                sample.append((rec, "degraded" if len(sample) % 2 else "clean"))
    sample = sample[:: max(1, len(sample) // max(1, n))][:n]
    stages: dict[str, list[float]] = defaultdict(list)
    totals = []
    for rec, variant in sample:
        path = DATA / rec["split"] / rec["files"][variant]
        mime = "image/png" if path.suffix == ".png" else "image/jpeg"
        t0 = time.perf_counter()
        out = pipe.run(path.read_bytes(), mime)
        totals.append((time.perf_counter() - t0) * 1000)
        for k, v in out.result.timings_ms.items():
            stages[k].append(v)
    return {"n": len(totals), "stages": {k: {"p50": quantile(v, 0.5), "p95": quantile(v, 0.95)} for k, v in stages.items()},
            "total": {"p50": quantile(totals, 0.5), "p95": quantile(totals, 0.95)}}  # fmt: skip


# --------------------------------------------------------------------------- main


def git_commit() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--system-n", type=int, default=20, help="documents for the end-to-end latency run (0 to skip)"
    )
    ap.add_argument("--bootstrap", type=int, default=500)
    args = ap.parse_args()
    frozen = check_frozen()
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = REPORTS / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    test_docs = [(rec, v) for s in SPLITS for rec in records(s) for v in VARIANTS]
    missing = [f"{rec['doc_id']}_{v}" for rec, v in test_docs if ocr_for(rec, v) is None]
    if missing:
        raise SystemExit(
            f"OCR cache missing for {len(missing)} test images (e.g. {missing[:3]}); run scripts/ocr_all.sh"
        )
    in_scope = [(rec, v) for rec, v in test_docs if rec["doc_type"] != "other"]
    print(f"test images: {len(test_docs)} ({len(in_scope)} receipts/invoices)")

    print("E1/E2 OCR ...")
    ocr_rows = eval_ocr()
    print("E3 classification ...")
    cls_rows, cls_preds = eval_classification(test_docs)
    tfidf_preds = cls_preds.get("TF-IDF + regresi logistik") or next(iter(cls_preds.values()))

    print("E4 extraction ...")
    engines = ["rules"] + [e for e in ("llm_ocr", "llm_vision") if (Path("data/cache/llm") / e).exists()]
    results = {e: extract_all(e, test_docs) for e in engines}
    subsets = [f"{s}/{v}" for s in SPLITS for v in VARIANTS]
    rows, per_doc_all = [], {}
    for e in engines:
        for sub in ["all", *subsets]:
            docs = in_scope if sub == "all" else [(r, v) for r, v in in_scope if f"{r['split']}/{v}" == sub]
            sc = score(docs, results[e])
            if sc["n"] == 0:
                continue
            per_doc = sc.pop("_per_doc")
            if sub == "all":
                per_doc_all[e] = per_doc
                for f in EVAL_FIELDS:
                    lo, hi = bootstrap_ci(per_doc, lambda d, f=f: f1_of(d, [f]), n_boot=args.bootstrap)
                    sc["fields"][f]["ci"] = [round(lo, 4), round(hi, 4)]
            rows.append({"subset": sub, "engine": e, **sc})
    methods = [{"engine": e, "label": ENGINE_LABELS[e], "available": e in engines,
                "note": None if e in engines else "belum dijalankan: perlu kredensial Claude API dan persetujuan biaya (ml.evaluation.llm_runs --yes)"}
               for e in ENGINE_LABELS]  # fmt: skip

    print("E5 confidence ...")
    confidence = eval_confidence(test_docs, results["rules"], tfidf_preds)
    print("E6 robustness ...")
    robustness = []
    for e in engines:
        for f in [
            *KEY_FIELDS,
            "subtotal",
            "tax_amount",
            "document_number",
            "vendor_tax_id",
            "discount",
            "due_date",
            "payment_method",
            "line_items",
        ]:
            vals = {}
            for v in VARIANTS:
                docs = [(r, vv) for r, vv in in_scope if vv == v]
                sc = score(docs, results[e])
                vals[v] = sc["line_items"]["f1"] if f == "line_items" else sc["fields"][f]["f1"]
            robustness.append({"engine": e, "field": f, "clean": vals["clean"], "degraded": vals["degraded"]})

    print("injection ...")
    injection = eval_injection(engines)
    print("error analysis ...")
    errors = error_analysis("rules", in_scope, results["rules"], out_dir)
    system = (
        eval_system(args.system_n)
        if args.system_n
        else {"n": 0, "stages": {}, "total": {"p50": None, "p95": None}}
    )

    rules_all = next(r for r in rows if r["engine"] == "rules" and r["subset"] == "all")
    best_cls = max((c for c in cls_rows if c["subset"] == "all"), key=lambda c: c["macro_f1"])
    key_f1 = f1_of(per_doc_all["rules"], KEY_FIELDS)
    tax_f1 = f1_of(per_doc_all["rules"], TAX_NO_FIELDS)
    dec = confidence["decision"]
    headline = {
        "total_f1": rules_all["fields"]["total"]["f1"], "key_fields_f1": round(key_f1, 4),
        "tax_docno_f1": round(tax_f1, 4), "line_items_f1": rules_all["line_items"]["f1"],
        "classification_macro_f1": best_cls["macro_f1"], "automation_rate": dec["automation_rate"],
        "auto_accuracy": dec["auto_accuracy"], "latency_p95_s": round(system["total"]["p95"] / 1000, 2) if system["total"]["p95"] else None,
        "ece_calibrated": confidence["methods"][2]["ece"] if len(confidence["methods"]) > 2 else None,
    }  # fmt: skip

    def tgt(
        metric: str, target: str, stretch: str, value: float | None, ok: bool | None, fmt: str = "{:.3f}"
    ) -> dict[str, Any]:
        return {
            "metric": metric,
            "target": target,
            "stretch": stretch,
            "value": "—" if value is None else fmt.format(value),
            "met": ok,
        }

    auto_ok = dec["auto_accuracy"] is not None and dec["auto_accuracy"] >= 0.98
    targets = [
        tgt("Klasifikasi jenis dokumen (macro-F1)", "≥ 0,90", "≥ 0,95", best_cls["macro_f1"], best_cls["macro_f1"] >= 0.90),
        tgt("F1 field utama (tanggal, vendor, total)", "≥ 0,90", "≥ 0,95", key_f1, key_f1 >= 0.90),
        tgt("F1 pajak dan nomor dokumen", "≥ 0,85", "≥ 0,90", tax_f1, tax_f1 >= 0.85),
        tgt("F1 item baris", "≥ 0,75", "≥ 0,85", rules_all["line_items"]["f1"], rules_all["line_items"]["f1"] >= 0.75),
        tgt("Lolos otomatis pada akurasi ≥ 98%", "≥ 50%", "≥ 70%", dec["automation_rate"], auto_ok and dec["automation_rate"] >= 0.5, "{:.1%}"),
        tgt("Waktu proses 1 halaman (p95)", "≤ 15 s", "≤ 8 s", headline["latency_p95_s"],
            None if headline["latency_p95_s"] is None else headline["latency_p95_s"] <= 15, "{:.1f} s"),
        tgt("Jumlah metode ekstraksi yang dibandingkan", "≥ 3", "≥ 4", float(len(engines)), len(engines) >= 3, "{:.0f}"),
    ]  # fmt: skip
    notes = [
        "Seluruh data uji adalah dokumen sintetis buatan sendiri. Angka ini mengukur kinerja pada distribusi generator, bukan pada nota nyata; hasil pada data nyata belum diukur.",
        "Aturan ekstraksi (metode A) disetel memakai dokumen train saja. Subset 'templat & vendor baru' memakai templat dan nama vendor yang tidak pernah muncul di train/val.",
    ]  # fmt: skip
    if dec["auto_accuracy"] is not None and dec["auto_accuracy"] < dec["target"]:
        names = {"test_seen/clean": "templat dikenal/bersih", "test_seen/degraded": "templat dikenal/terdegradasi",
                 "test_unseen/clean": "templat baru/bersih", "test_unseen/degraded": "templat baru/terdegradasi"}  # fmt: skip
        below = [f"{names[k]} ({v['auto_accuracy']:.1%} pada coverage {v['automation_rate']:.1%})"
                 for k, v in dec["by_subset"].items() if v["auto_accuracy"] is not None and v["auto_accuracy"] < dec["target"]]  # fmt: skip
        none = [names[k] for k, v in dec["by_subset"].items() if v["n_auto"] == 0]
        text = (f"Ambang otomatis dipilih di data validasi dan menghasilkan akurasi {dec['auto_accuracy']:.1%} di data uji, "
                f"di bawah target {dec['target']:.0%}.")  # fmt: skip
        if below:
            text += " Subset di bawah target: " + "; ".join(below) + "."
        if none:
            text += (
                " Tidak ada dokumen yang lolos otomatis pada: "
                + ", ".join(none)
                + " (aman, tetapi tanpa otomasi)."
            )
        notes.append(text)
    if injection["detected_rate"] < 1:
        notes.append(
            f"Pemindai prompt injection hanya mendeteksi {injection['detected_rate']:.0%} dokumen uji injeksi: teks injeksi "
            "berukuran kecil sering tidak terbaca OCR pada gambar terdegradasi. Mesin aturan tidak terpengaruh isi instruksi, "
            f"tetapi {injection['auto_approved']} dokumen berinstruksi tetap lolos otomatis."
        )
    if len(engines) < 3:
        notes.append(
            "Metode B dan C (Claude API) belum dievaluasi pada run ini; tabel hanya memuat metode yang benar-benar dijalankan."
        )

    summary = {
        "run_id": run_id, "created_at": datetime.now(UTC).isoformat(), "git_commit": git_commit(),
        "duration_s": round(time.time() - t_start, 1),
        "dataset": {"name": "DokuData sintetis v1", "seed": frozen["seed"], "splits": frozen["splits"]},
        "notes": notes, "headline": headline, "targets": targets,
        "extraction": {"subsets": subsets, "methods": methods, "rows": rows},
        "ocr": ocr_rows, "classification": {"methods": cls_rows}, "confidence": confidence,
        "robustness": robustness, "injection": injection, "errors": errors, "system": system,
        "thresholds": decision_config(),
    }  # fmt: skip
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    latest = REPORTS / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    shutil.copytree(out_dir, latest)
    write_report(summary, Path("docs/evaluation-report.md"), latest)
    write_model_card(summary, Path("docs/model-card.md"))
    _mlflow(summary)
    print(json.dumps(headline, indent=1))
    print(f"wrote {out_dir} and docs/evaluation-report.md in {time.time() - t_start:.0f}s")


def _mlflow(summary: dict[str, Any]) -> None:
    """Log the run to MLflow when it is installed (optional dependency)."""
    try:
        import mlflow
    except ImportError:
        return
    mlflow.set_experiment("dokudata-eval")
    with mlflow.start_run(run_name=summary["run_id"]):
        mlflow.log_params(
            {
                "dataset_seed": summary["dataset"]["seed"],
                **{f"threshold_{k}": v for k, v in summary["thresholds"].items()},
            }
        )
        mlflow.log_metrics({k: v for k, v in summary["headline"].items() if isinstance(v, int | float)})
        mlflow.log_artifacts(str(REPORTS / "latest"))


if __name__ == "__main__":
    main()
