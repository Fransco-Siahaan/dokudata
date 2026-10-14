"""Locate an extracted value in the OCR words.

Used for two things: drawing the highlight box in the review screen, and the
hallucination check from PRD 16.3 (a value the model claims must actually
appear in the document).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from rapidfuzz import fuzz

from pipeline.interfaces import BBox, Line, OCRDocument, merge_bboxes
from pipeline.normalize import find_dates, parse_amount, text_key


@dataclass(slots=True)
class Grounding:
    found: bool
    score: float = 0.0
    bbox: BBox | None = None
    page: int | None = None
    ocr_conf: float | None = None
    line_index: int | None = None


NOT_FOUND = Grounding(False)


def _windows(line: Line, max_len: int) -> list[tuple[int, int]]:
    n = len(line.words)
    return [(i, j) for i in range(n) for j in range(i + 1, min(n, i + max_len) + 1)]


def _result(line: Line, i: int, j: int, score: float, idx: int) -> Grounding:
    words = line.words[i:j]
    return Grounding(
        True,
        score,
        merge_bboxes([w.bbox for w in words]),
        line.page,
        float(np.mean([w.conf for w in words])),
        idx,
    )


def ground_amount(lines: list[Line], value: float, prefer_last: bool = False) -> Grounding:
    hits: list[Grounding] = []
    for idx, line in enumerate(lines):
        for i, j in _windows(line, 3):
            raw = " ".join(w.text for w in line.words[i:j])
            if j - i > 1 and not raw.lower().startswith(("rp", "idr")):
                continue
            parsed = parse_amount(raw)
            if parsed is not None and abs(parsed - value) < 0.005:
                hits.append(_result(line, i, j, 1.0, idx))
                break
    if not hits:
        return NOT_FOUND
    return hits[-1] if prefer_last else hits[0]


def ground_date(lines: list[Line], iso: str) -> Grounding:
    for idx, line in enumerate(lines):
        for i, j in _windows(line, 4):
            raw = " ".join(w.text for w in line.words[i:j])
            if any(m.iso == iso and len(m.raw) >= len(raw) - 2 for m in find_dates(raw)):
                return _result(line, i, j, 1.0, idx)
    return NOT_FOUND


def ground_text(lines: list[Line], target: str, threshold: float = 80.0) -> Grounding:
    key = text_key(target)
    if not key:
        return NOT_FOUND
    best = NOT_FOUND
    n_tokens = max(1, len(target.split()))
    for idx, line in enumerate(lines):
        for i, j in _windows(line, n_tokens + 2):
            cand = text_key(" ".join(w.text for w in line.words[i:j]))
            if not cand:
                continue
            score = fuzz.ratio(key, cand)
            if score > best.score and score >= threshold:
                best = _result(line, i, j, score / 100.0, idx)
    return best


def ground_value(ocr: OCRDocument | None, kind: str, value: object, raw: str | None = None) -> Grounding:
    """Ground a value of ``kind`` ('amount' | 'date' | 'text')."""
    if ocr is None or value is None:
        return NOT_FOUND
    lines = ocr.lines()
    if kind == "amount" and isinstance(value, int | float):
        return ground_amount(lines, float(value), prefer_last=True)
    if kind == "date" and isinstance(value, str):
        g = ground_date(lines, value)
        if not g.found and raw:
            g = ground_text(lines, raw)
        return g
    if kind == "text":
        g = ground_text(lines, str(value))
        if not g.found and raw and raw != value:
            g = ground_text(lines, raw)
        return g
    return NOT_FOUND
