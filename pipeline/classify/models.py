"""Document-type classifiers (PRD 8.3): keyword fallback, TF-IDF + LR, embeddings + LR.

Classes are ``receipt``, ``invoice`` and ``other``. The ``other`` class lets the
system refuse out-of-scope pages instead of forcing them into a schema.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from pipeline.config import MODELS_DIR
from pipeline.interfaces import ClassificationResult
from pipeline.schema import DOC_TYPES

EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def _clean(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\d", "0", text)  # digits carry layout signal, not identity
    return re.sub(r"\s+", " ", text)


class KeywordClassifier:
    """Zero-training fallback so the app works before any model is trained."""

    name = "keywords"
    labels = DOC_TYPES
    KEYWORDS = {
        "receipt": ["struk", "kasir", "tunai", "kembali", "terima kasih", "nota", "bayar", "total belanja", "pelayan",
                    "meja", "transaksi", "merchant", "qris", "ksr"],
        "invoice": ["invoice", "faktur", "jatuh tempo", "tagihan", "kepada yth", "bill to", "due date", "rekening",
                    "terbilang", "hormat kami", "termin", "amount due"],
        "other": ["perihal", "undangan", "surat", "pengumuman", "riwayat hidup", "pendidikan", "notulen", "daftar harga",
                  "surat jalan", "menerangkan", "acara", "peserta"],
    }  # fmt: skip

    def predict(self, text: str) -> ClassificationResult:
        low = text.lower()
        scores = {lab: sum(low.count(k) for k in kws) for lab, kws in self.KEYWORDS.items()}
        has_money = len(re.findall(r"\d{1,3}(?:[.,]\d{3})+", text)) >= 3
        scores["other"] += 0 if has_money else 2
        exps = {k: math.exp(min(v, 20) * 0.7) for k, v in scores.items()}
        z = sum(exps.values())
        probs = {k: v / z for k, v in exps.items()}
        label = max(probs, key=lambda k: probs[k])
        return ClassificationResult(label, probs, self.name)


class SklearnTextClassifier:
    """TF-IDF (word 1-2 grams + char 2-5 grams) with logistic regression."""

    name = "tfidf"
    labels = DOC_TYPES

    def __init__(self, pipeline: Any = None) -> None:
        self.pipeline = pipeline

    @staticmethod
    def build() -> Any:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import FeatureUnion, Pipeline

        features = FeatureUnion([
            ("word", TfidfVectorizer(preprocessor=_clean, ngram_range=(1, 2), min_df=2, sublinear_tf=True)),
            ("char", TfidfVectorizer(preprocessor=_clean, analyzer="char_wb", ngram_range=(2, 5), min_df=3,
                                     sublinear_tf=True, max_features=60000)),
        ])  # fmt: skip
        return Pipeline(
            [
                ("features", features),
                ("lr", LogisticRegression(C=8.0, max_iter=2000, class_weight="balanced")),
            ]
        )

    def fit(self, texts: list[str], labels: list[str]) -> SklearnTextClassifier:
        self.pipeline = self.build().fit(texts, labels)
        return self

    def predict(self, text: str) -> ClassificationResult:
        proba = self.pipeline.predict_proba([text])[0]
        probs = {str(c): float(p) for c, p in zip(self.pipeline.classes_, proba, strict=True)}
        label = max(probs, key=lambda k: probs[k])
        return ClassificationResult(label, probs, self.name)

    def predict_many(self, texts: list[str]) -> list[ClassificationResult]:
        proba = self.pipeline.predict_proba(texts)
        out = []
        for row in proba:
            probs = {str(c): float(p) for c, p in zip(self.pipeline.classes_, row, strict=True)}
            out.append(ClassificationResult(max(probs, key=lambda k: probs[k]), probs, self.name))
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, path)

    @classmethod
    def load(cls, path: Path) -> SklearnTextClassifier:
        return cls(joblib.load(path))


class EmbeddingClassifier:
    """Multilingual sentence embeddings with logistic regression."""

    name = "embedding"
    labels = DOC_TYPES
    _encoders: dict[str, Any] = {}

    def __init__(self, lr: Any = None, model_name: str = EMBEDDING_MODEL) -> None:
        self.lr = lr
        self.model_name = model_name

    def _encoder(self) -> Any:
        if self.model_name not in self._encoders:
            from sentence_transformers import SentenceTransformer

            self._encoders[self.model_name] = SentenceTransformer(self.model_name, device="cpu")
        return self._encoders[self.model_name]

    def embed(self, texts: list[str]) -> np.ndarray:
        # The model reads 128 word pieces; the top of a page (header, title) carries most of the type signal.
        trimmed = [" ".join(t.split()[:120]) for t in texts]
        return np.asarray(self._encoder().encode(trimmed, batch_size=32, normalize_embeddings=True))

    def fit(
        self, texts: list[str], labels: list[str], embeddings: np.ndarray | None = None
    ) -> EmbeddingClassifier:
        from sklearn.linear_model import LogisticRegression

        x = embeddings if embeddings is not None else self.embed(texts)
        self.lr = LogisticRegression(C=4.0, max_iter=3000, class_weight="balanced").fit(x, labels)
        return self

    def predict(self, text: str) -> ClassificationResult:
        return self.predict_embeddings(self.embed([text]))[0]

    def predict_embeddings(self, x: np.ndarray) -> list[ClassificationResult]:
        out = []
        for row in self.lr.predict_proba(x):
            probs = {str(c): float(p) for c, p in zip(self.lr.classes_, row, strict=True)}
            out.append(ClassificationResult(max(probs, key=lambda k: probs[k]), probs, self.name))
        return out

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"lr": self.lr, "model_name": self.model_name}, path)

    @classmethod
    def load(cls, path: Path) -> EmbeddingClassifier:
        obj = joblib.load(path)
        return cls(obj["lr"], obj["model_name"])


def load_classifier(name: str = "tfidf", models_dir: Path | None = None) -> Any:
    """Load a trained classifier, falling back to keywords when no model file exists."""
    d = models_dir or MODELS_DIR
    if name == "tfidf" and (d / "classifier_tfidf.joblib").exists():
        return SklearnTextClassifier.load(d / "classifier_tfidf.joblib")
    if name == "embedding" and (d / "classifier_embedding.joblib").exists():
        return EmbeddingClassifier.load(d / "classifier_embedding.joblib")
    return KeywordClassifier()
