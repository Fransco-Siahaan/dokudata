from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from pipeline.interfaces import OCRDocument, OCRPage, Word
from pipeline.schema import Extraction


def make_ocr(rows: list[str], line_height: int = 20) -> OCRDocument:
    """Fake OCR output: one row per string, words spaced evenly, wide gaps on double spaces."""
    words: list[Word] = []
    for i, row in enumerate(rows):
        x = 10.0
        y = 10.0 + i * (line_height + 8)
        for chunk in row.split("  "):
            for tok in chunk.split():
                w = 9.0 * len(tok)
                words.append(Word(tok, (x, y, x + w, y + line_height), 0.98))
                x += w + 6
            x += 60  # column gap
    return OCRDocument([OCRPage(words, 600, 40 + len(rows) * (line_height + 8), "fake")])


def good_values() -> dict:
    return {
        "vendor_name": "Toko Maju Jaya",
        "vendor_tax_id": None,
        "document_number": "NT-0231",
        "issue_date": "2026-03-14",
        "due_date": None,
        "currency": "IDR",
        "subtotal": 244000.0,
        "discount": None,
        "tax_amount": 26840.0,
        "total": 270840.0,
        "payment_method": "cash",
        "line_items": [
            {"description": "Beras 5 kg", "qty": 2, "unit_price": 65000, "amount": 130000},
            {"description": "Minyak goreng 2 L", "qty": 3, "unit_price": 38000, "amount": 114000},
        ],
    }


@pytest.fixture
def good_extraction() -> Extraction:
    return Extraction.from_values(good_values(), source="test")


@pytest.fixture
def today() -> date:
    return date(2026, 10, 11)


@pytest.fixture
def blank_image() -> np.ndarray:
    return np.full((400, 300, 3), 255, np.uint8)
