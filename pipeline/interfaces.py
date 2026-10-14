"""Shared contracts for every swappable engine in the pipeline.

Each stage (OCR, classification, extraction) sits behind a small Protocol so an
experiment is just a configuration change: the evaluation harness and the API
worker both build engines from names via :mod:`pipeline.registry`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

from pipeline.schema import Extraction

BBox = tuple[float, float, float, float]  # x0, y0, x1, y1 in page-image pixels


@dataclass(slots=True)
class Word:
    text: str
    bbox: BBox
    conf: float
    page: int = 0


@dataclass(slots=True)
class Line:
    words: list[Word]
    page: int = 0

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def bbox(self) -> BBox:
        return merge_bboxes([w.bbox for w in self.words])

    @property
    def conf(self) -> float:
        return float(np.mean([w.conf for w in self.words])) if self.words else 0.0


@dataclass(slots=True)
class OCRPage:
    words: list[Word]
    width: int
    height: int
    engine: str
    page: int = 0
    elapsed_ms: float = 0.0

    def lines(self) -> list[Line]:
        return group_lines(self.words, self.page)

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines())


@dataclass(slots=True)
class OCRDocument:
    pages: list[OCRPage]

    @property
    def engine(self) -> str:
        return self.pages[0].engine if self.pages else "none"

    @property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    def lines(self) -> list[Line]:
        return [line for p in self.pages for line in p.lines()]

    @property
    def words(self) -> list[Word]:
        return [w for p in self.pages for w in p.words]

    @property
    def elapsed_ms(self) -> float:
        return sum(p.elapsed_ms for p in self.pages)


@dataclass(slots=True)
class ClassificationResult:
    label: str
    probabilities: dict[str, float]
    engine: str

    @property
    def confidence(self) -> float:
        return self.probabilities.get(self.label, 0.0)


@dataclass(slots=True)
class ExtractionInput:
    images: list[np.ndarray]  # preprocessed page images (BGR)
    ocr: OCRDocument | None
    doc_type: str


@dataclass(slots=True)
class ExtractionResult:
    extraction: Extraction
    engine: str
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    meta: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class OCREngine(Protocol):
    name: str

    def recognize(self, image: np.ndarray, page: int = 0) -> OCRPage: ...


@runtime_checkable
class Classifier(Protocol):
    name: str
    labels: list[str]

    def predict(self, text: str) -> ClassificationResult: ...


@runtime_checkable
class Extractor(Protocol):
    name: str
    requires_ocr: bool

    def extract(self, inp: ExtractionInput) -> ExtractionResult: ...


def merge_bboxes(boxes: list[BBox]) -> BBox:
    if not boxes:
        return (0.0, 0.0, 0.0, 0.0)
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def group_lines(words: list[Word], page: int = 0) -> list[Line]:
    """Group words into visual rows by vertical overlap, then sort left-to-right.

    OCR engines report text in their own detection order (RapidOCR returns
    detection boxes, which split table columns apart). Rebuilding rows from
    geometry gives every engine the same reading order.
    """
    if not words:
        return []

    def mid(w: Word) -> float:
        return (w.bbox[1] + w.bbox[3]) / 2

    def height(w: Word) -> float:
        return max(1.0, w.bbox[3] - w.bbox[1])

    ordered = sorted(words, key=lambda w: (mid(w), w.bbox[0]))
    rows: list[list[Word]] = []
    for w in ordered:
        best, best_d = -1, float("inf")
        # Compare with the horizontally nearest word of each recent row: robust to residual
        # skew, and a tall title cannot swallow the small lines printed beside it.
        for r in range(max(0, len(rows) - 4), len(rows)):
            nearest = min(
                rows[r], key=lambda o: abs((o.bbox[0] + o.bbox[2]) / 2 - (w.bbox[0] + w.bbox[2]) / 2)
            )
            d = abs(mid(nearest) - mid(w))
            if d <= 0.5 * min(height(w), height(nearest)) and d < best_d:
                best, best_d = r, d
        if best >= 0:
            rows[best].append(w)
        else:
            rows.append([w])
    lines = [Line(words=sorted(r, key=lambda w: w.bbox[0]), page=page) for r in rows]
    lines.sort(key=lambda ln: min(mid(w) for w in ln.words))
    return lines
