"""Render template HTML to PDF and PNG with PyMuPDF's Story engine (no browser needed)."""

from __future__ import annotations

import io

import cv2
import numpy as np
import pymupdf

from ml.synthetic.templates import Page
from pipeline.interfaces import Word, group_lines


def html_to_pdf(html: str, css: str, page: Page) -> bytes:
    content_w = page.width - 2 * page.margin
    height = page.height
    if height is None:
        # Measure pass: place the story in a very tall box, then size the page to fit.
        probe = pymupdf.Story(html=html, user_css=css)
        _, filled = probe.place(pymupdf.Rect(0, 0, content_w, 5000))
        height = filled[3] + 2 * page.margin
    rect = pymupdf.Rect(0, 0, page.width, height)
    story = pymupdf.Story(html=html, user_css=css)
    buf = io.BytesIO()
    writer = pymupdf.DocumentWriter(buf)
    more = 1
    while more:
        dev = writer.begin_page(rect)
        more, _ = story.place(rect + (page.margin, page.margin, -page.margin, -page.margin))
        story.draw(dev)
        writer.end_page()
    writer.close()
    return buf.getvalue()


def pdf_to_image(pdf: bytes, dpi: int) -> np.ndarray:
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    pix = doc[0].get_pixmap(dpi=dpi, colorspace=pymupdf.csRGB, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def reference_text(pdf: bytes) -> str:
    """Reading-order text of the first page, built with the same line grouping OCR output uses."""
    doc = pymupdf.open(stream=pdf, filetype="pdf")
    words = [
        Word(t, (x0, y0, x1, y1), 1.0) for x0, y0, x1, y1, t, *_ in doc[0].get_text("words") if t.strip()
    ]
    return "\n".join(line.text for line in group_lines(words))
