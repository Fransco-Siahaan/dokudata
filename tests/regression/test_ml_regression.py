"""ML regression gate (PRD 17.2): metrics on a small fixed set must not fall below their floors.

Thirty documents are regenerated from fixed seeds and read through their PDF
text layer (no OCR model needed), so the test is fast and deterministic. A
heuristic change that breaks extraction fails CI here before it reaches the
full evaluation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ml.evaluation.metrics import EVAL_FIELDS, Counts, field_counts, match_line_items
from ml.synthetic.generate import make_document
from pipeline.extract.rules import RulesExtractor
from pipeline.interfaces import ExtractionInput
from pipeline.ocr import pdf_text_layer

FLOORS = {"vendor_name": 0.95, "issue_date": 0.97, "total": 0.97, "subtotal": 0.95, "tax_amount": 0.95,
          "document_number": 0.9, "line_items": 0.95}  # fmt: skip


@pytest.mark.regression
def test_rules_extractor_meets_floors(tmp_path: Path):
    counts = {f: Counts() for f in EVAL_FIELDS}
    items = Counts()
    n = 0
    for i in range(30):
        row = make_document(424242, "regression", i, str(tmp_path))
        rec = json.loads((tmp_path / "regression" / f"{row['doc_id']}.json").read_text(encoding="utf-8"))
        if rec["doc_type"] == "other":
            continue
        n += 1
        ocr = pdf_text_layer((tmp_path / "regression" / rec["files"]["pdf"]).read_bytes(), dpi=150)
        pred = RulesExtractor().extract(ExtractionInput([], ocr, rec["doc_type"])).extraction.values()
        gt = rec["ground_truth"]
        for f in EVAL_FIELDS:
            counts[f].add(field_counts(f, pred.get(f), gt.get(f)))
        c, _ = match_line_items(pred["line_items"], gt["line_items"])
        items.add(c)
    assert n >= 15
    scores = {f: counts[f].f1 for f in EVAL_FIELDS} | {"line_items": items.f1}
    failing = {f: round(scores[f], 3) for f, floor in FLOORS.items() if scores[f] < floor}
    assert not failing, f"below regression floors: {failing}"
