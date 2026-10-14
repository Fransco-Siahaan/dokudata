"""Train the document-type classifiers on OCR text of the train split (experiment E3).

    python -m ml.training.train_classifier [--no-embedding]

Model selection uses the validation split only; the test splits are untouched.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from ml.common import records
from ml.evaluation.harness import ocr_for
from ml.evaluation.metrics import classification_report
from pipeline.classify import EmbeddingClassifier, KeywordClassifier, SklearnTextClassifier
from pipeline.config import MODELS_DIR
from pipeline.schema import DOC_TYPES

REPORT = Path("reports/training/classifier.json")


def texts_labels(split: str) -> tuple[list[str], list[str]]:
    texts, labels = [], []
    for rec in records(split):
        ocr = ocr_for(rec, "primary")
        if ocr is None:
            raise SystemExit(
                f"OCR cache missing for {split}/{rec['doc_id']}: run ml.evaluation.ocr_cache first"
            )
        texts.append(ocr.text)
        labels.append(rec["doc_type"])
    return texts, labels


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-embedding", action="store_true")
    args = ap.parse_args()
    x_tr, y_tr = texts_labels("train")
    x_va, y_va = texts_labels("val")
    report: dict[str, object] = {"train_n": len(x_tr), "val_n": len(x_va)}

    kw = KeywordClassifier()
    report["keywords"] = classification_report(y_va, [kw.predict(t).label for t in x_va], DOC_TYPES)

    t0 = time.time()
    tfidf = SklearnTextClassifier().fit(x_tr, y_tr)
    pred = [r.label for r in tfidf.predict_many(x_va)]
    report["tfidf"] = {
        **classification_report(y_va, pred, DOC_TYPES),
        "train_seconds": round(time.time() - t0, 1),
    }
    tfidf.save(MODELS_DIR / "classifier_tfidf.joblib")
    print(f"tfidf     val macro-F1={report['tfidf']['macro_f1']:.4f}")  # type: ignore[index]

    if not args.no_embedding:
        t0 = time.time()
        emb = EmbeddingClassifier()
        e_tr, e_va = emb.embed(x_tr), emb.embed(x_va)
        np.save(MODELS_DIR / "embeddings_val.npy", e_va)
        emb.fit(x_tr, y_tr, embeddings=e_tr)
        pred = [r.label for r in emb.predict_embeddings(e_va)]
        report["embedding"] = {**classification_report(y_va, pred, DOC_TYPES), "model": emb.model_name,
                               "train_seconds": round(time.time() - t0, 1)}  # fmt: skip
        emb.save(MODELS_DIR / "classifier_embedding.joblib")
        print(f"embedding val macro-F1={report['embedding']['macro_f1']:.4f}")  # type: ignore[index]
    print(f"keywords  val macro-F1={report['keywords']['macro_f1']:.4f}")  # type: ignore[index]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
