"""OCR engines behind the :class:`~pipeline.interfaces.OCREngine` contract (PRD 8.2)."""

from __future__ import annotations

import os
import shutil
import threading
import time
from typing import Any

import numpy as np

from pipeline.interfaces import OCRDocument, OCRPage, Word


class OCRUnavailableError(RuntimeError):
    pass


class RapidOCREngine:
    """PaddleOCR (PP-OCR) detection + recognition models running on ONNX Runtime (CPU)."""

    name = "rapidocr"
    _lock = threading.Lock()
    _run_lock = threading.Lock()
    _shared: Any = None

    def __init__(self) -> None:
        with RapidOCREngine._lock:
            if RapidOCREngine._shared is None:
                from rapidocr import RapidOCR

                # Several worker processes share the CPU; unbounded ONNX threads oversubscribe it.
                threads = int(os.environ.get("DOKUDATA_OCR_THREADS", "2"))
                RapidOCREngine._shared = RapidOCR(
                    params={
                        "Global.log_level": "error",
                        "EngineConfig.onnxruntime.intra_op_num_threads": threads,
                    }
                )
        self._engine = RapidOCREngine._shared

    def recognize(self, image: np.ndarray, page: int = 0) -> OCRPage:
        start = time.perf_counter()
        with RapidOCREngine._run_lock:  # one RapidOCR instance is shared by the API's worker threads
            result = self._engine(image, return_word_box=True)
        words: list[Word] = []
        word_results = getattr(result, "word_results", None) or ()
        if word_results:
            for line in word_results:
                for text, score, box in line:
                    if not str(text).strip():
                        continue
                    xs = [p[0] for p in box]
                    ys = [p[1] for p in box]
                    words.append(Word(str(text), (min(xs), min(ys), max(xs), max(ys)), float(score), page))
        elif result.boxes is not None:
            for text, score, box in zip(result.txts, result.scores, result.boxes, strict=False):
                words.extend(_split_line_box(str(text), np.asarray(box), float(score), page))
        h, w = image.shape[:2]
        return OCRPage(words, w, h, self.name, page, (time.perf_counter() - start) * 1000)


def _split_line_box(text: str, box: np.ndarray, score: float, page: int) -> list[Word]:
    """Approximate word boxes from a line box by character share."""
    x0, y0 = box[:, 0].min(), box[:, 1].min()
    x1, y1 = box[:, 0].max(), box[:, 1].max()
    tokens = text.split()
    total = max(1, len(text))
    out: list[Word] = []
    cursor = 0
    for tok in tokens:
        idx = text.find(tok, cursor)
        cursor = idx + len(tok)
        a = x0 + (x1 - x0) * idx / total
        b = x0 + (x1 - x0) * cursor / total
        out.append(Word(tok, (float(a), float(y0), float(b), float(y1)), score, page))
    return out


class TesseractEngine:
    """Classic Tesseract baseline (needs the ``tesseract`` binary with ``ind`` + ``eng`` data)."""

    name = "tesseract"

    def __init__(self, lang: str = "ind+eng") -> None:
        if shutil.which("tesseract") is None:
            raise OCRUnavailableError("tesseract binary not found on PATH")
        import pytesseract

        self._tess = pytesseract
        available = set(pytesseract.get_languages(config=""))
        wanted = [code for code in lang.split("+") if code in available]
        self.lang = "+".join(wanted) or "eng"

    def recognize(self, image: np.ndarray, page: int = 0) -> OCRPage:
        start = time.perf_counter()
        data = self._tess.image_to_data(
            image, lang=self.lang, config="--psm 6", output_type=self._tess.Output.DICT
        )
        words = []
        for i, text in enumerate(data["text"]):
            conf = float(data["conf"][i])
            if not text.strip() or conf < 0:
                continue
            x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
            words.append(Word(text, (float(x), float(y), float(x + w), float(y + h)), conf / 100.0, page))
        h, w = image.shape[:2]
        return OCRPage(words, w, h, self.name, page, (time.perf_counter() - start) * 1000)


def pdf_text_layer(data: bytes, dpi: int = 200) -> OCRDocument | None:
    """Words from a digital PDF's text layer, scaled to the rendered page image.

    Digital (non-scanned) PDFs already carry exact text and positions, so OCR is
    skipped for them. Returns ``None`` for scanned PDFs (no meaningful text).
    """
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    scale = dpi / 72.0
    pages: list[OCRPage] = []
    total_chars = 0
    for i in range(doc.page_count):
        page = doc[i]
        start = time.perf_counter()
        words = [
            Word(t, (x0 * scale, y0 * scale, x1 * scale, y1 * scale), 1.0, i)
            for x0, y0, x1, y1, t, *_ in page.get_text("words")
            if t.strip()
        ]
        total_chars += sum(len(w.text) for w in words)
        width, height = int(page.rect.width * scale), int(page.rect.height * scale)
        pages.append(OCRPage(words, width, height, "pdf_text", i, (time.perf_counter() - start) * 1000))
    if total_chars < 20 * max(1, len(pages)):
        return None
    return OCRDocument(pages)


_ENGINES: dict[str, type] = {"rapidocr": RapidOCREngine, "tesseract": TesseractEngine}


def available_ocr_engines() -> list[str]:
    names = ["rapidocr"]
    if shutil.which("tesseract"):
        names.append("tesseract")
    return names


def get_ocr_engine(name: str) -> Any:
    if name == "llm_vision":
        from pipeline.ocr.llm_ocr import ClaudeVisionOCR

        return ClaudeVisionOCR()
    try:
        return _ENGINES[name]()
    except KeyError as exc:
        raise ValueError(f"unknown OCR engine {name!r}") from exc


def run_ocr(engine: Any, images: list[np.ndarray]) -> OCRDocument:
    return OCRDocument([engine.recognize(img, page=i) for i, img in enumerate(images)])
