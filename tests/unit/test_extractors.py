from __future__ import annotations

import copy
from typing import Any

import pytest

from pipeline.extract.llm import LLM_SCHEMA, OCRLLMExtractor, VisionLLMExtractor
from pipeline.extract.rules import RulesExtractor
from pipeline.interfaces import ExtractionInput
from pipeline.llm import FakeLLMClient, LLMError
from tests.conftest import make_ocr

RECEIPT_ROWS = [
    "TOKO MAJU JAYA",
    "Jl. Merdeka No. 12, Bandung",
    "NPWP: 01.234.567.8-901.234",
    "No: NT-0231  14/03/2026",
    "Beras 5 kg",
    "2 x 65.000  130.000",
    "Minyak goreng 2 L",
    "3 x 38.000  114.000",
    "SUBTOTAL  244.000",
    "PPN 11%  26.840",
    "TOTAL  270.840",
    "TUNAI  300.000",
    "KEMBALI  29.160",
]


def answer(**overrides: Any) -> dict[str, Any]:
    def f(value: Any, src: str | None = None) -> dict[str, Any]:
        return {"value": value, "source_text": src}

    base = {
        "document_type": "receipt",
        "vendor_name": f("TOKO MAJU JAYA", "TOKO MAJU JAYA"),
        "vendor_tax_id": f("01.234.567.8-901.234", "01.234.567.8-901.234"),
        "document_number": f("NT-0231", "NT-0231"),
        "issue_date": f("2026-03-14", "14/03/2026"),
        "due_date": f(None),
        "currency": f("IDR"),
        "payment_method": f("cash", "TUNAI"),
        "subtotal": f(244000, "244.000"),
        "discount": f(None),
        "tax_amount": f(26840, "26.840"),
        "total": f(270840, "270.840"),
        "line_items": [
            {"description": "Beras 5 kg", "qty": 2, "unit_price": 65000, "amount": 130000},
            {"description": "Minyak goreng 2 L", "qty": 3, "unit_price": 38000, "amount": 114000},
        ],
        "suspicious_instructions": False,
    }
    base.update(overrides)
    return base


def test_rules_extractor_on_receipt():
    ex = RulesExtractor().extract(ExtractionInput([], make_ocr(RECEIPT_ROWS), "receipt")).extraction
    v = ex.values()
    assert v["vendor_name"] == "Toko Maju Jaya"
    assert v["document_number"] == "NT-0231"
    assert v["issue_date"] == "2026-03-14"
    assert v["vendor_tax_id"] == "012345678901234"
    assert (v["subtotal"], v["tax_amount"], v["total"]) == (244000.0, 26840.0, 270840.0)
    assert v["payment_method"] == "cash"
    assert [(i["description"], i["qty"], i["amount"]) for i in v["line_items"]] == [
        ("Beras 5 kg", 2.0, 130000.0),
        ("Minyak goreng 2 L", 3.0, 114000.0),
    ]
    assert ex.total.bbox is not None  # used to highlight the field in the review screen


def test_rules_never_takes_cash_tendered_as_total():
    rows = [r for r in RECEIPT_ROWS if not r.startswith(("SUBTOTAL", "PPN"))]
    rows[rows.index("TOTAL  270.840")] = "TOTAL  244.000"
    v = RulesExtractor().extract(ExtractionInput([], make_ocr(rows), "receipt")).extraction.values()
    assert v["total"] == 244000.0


def test_llm_ocr_extractor_normalises_and_grounds():
    client = FakeLLMClient(lambda _s, _c: answer())
    res = OCRLLMExtractor(client).extract(ExtractionInput([], make_ocr(RECEIPT_ROWS), "receipt"))
    v = res.extraction.values()
    assert v["vendor_name"] == "Toko Maju Jaya"
    assert v["vendor_tax_id"] == "012345678901234"
    assert v["total"] == 270840.0
    assert all(res.meta["grounded"].values())
    assert res.extraction.total.confidence == 0.9 and res.extraction.total.bbox
    # The document goes in as data inside <document> tags, and the schema is strict.
    sent = client.calls[0]
    assert "<document>" in sent["content"][0]["text"]
    assert sent["schema"] == LLM_SCHEMA and sent["schema"]["additionalProperties"] is False


def test_llm_value_missing_from_document_is_flagged_as_hallucination():
    client = FakeLLMClient(lambda _s, _c: answer(total={"value": 999999, "source_text": "999.999"}))
    res = OCRLLMExtractor(client).extract(ExtractionInput([], make_ocr(RECEIPT_ROWS), "receipt"))
    assert res.meta["grounded"]["total"] is False
    assert res.extraction.total.confidence < 0.5


def test_llm_invalid_output_is_retried_then_fails():
    bad = copy.deepcopy(answer())
    del bad["total"]
    calls = {"n": 0}

    def responder(_s, _c):
        calls["n"] += 1
        return bad if calls["n"] == 1 else answer()

    res = OCRLLMExtractor(FakeLLMClient(responder)).extract(
        ExtractionInput([], make_ocr(RECEIPT_ROWS), "receipt")
    )
    assert res.meta["attempts"] == 2 and res.extraction.total.value == 270840.0
    with pytest.raises(LLMError):
        OCRLLMExtractor(FakeLLMClient(lambda _s, _c: bad)).extract(
            ExtractionInput([], make_ocr(RECEIPT_ROWS), "receipt")
        )


def test_vision_extractor_sends_image_and_reports_injection(blank_image):
    client = FakeLLMClient(lambda _s, _c: answer(suspicious_instructions=True))
    res = VisionLLMExtractor(client).extract(ExtractionInput([blank_image], None, "receipt"))
    assert client.calls[0]["content"][0]["type"] == "image"
    assert res.meta["suspicious_instructions"] is True
    assert res.extraction.total.confidence == 0.8  # no OCR to ground against


def test_pipeline_falls_back_to_rules_when_llm_fails(blank_image):
    from pipeline.runner import Pipeline, PipelineConfig

    def boom(_s, _c):
        raise LLMError("service down")

    pipe = Pipeline(
        PipelineConfig(extractor="llm_ocr", classifier="keywords"), llm_client=FakeLLMClient(boom)
    )
    out = pipe.run_from_ocr([blank_image], make_ocr(RECEIPT_ROWS))
    assert out.result.engines["extractor"] == "rules"
    assert out.result.decision == "needs_review"
    assert any("gagal" in f for f in out.result.flags)
    assert out.result.thresholds["field"] > 0  # the review screen colours confidence with this


def test_invoice_row_number_is_not_a_quantity():
    from pipeline.extract.rules import _parse_item_line

    line = make_ocr(["3  Langganan internet 50  475.000,-  950.000,-"]).lines()[0]
    desc, qty, price, amount, _ = _parse_item_line(line, row_no=3)
    assert " ".join(w.text for w in desc) == "Langganan internet 50"
    assert (qty, price, amount) == (2, 475000.0, 950000.0)
    # In a restaurant bill a leading number that is not the row number stays the quantity.
    line = make_ocr(["4 Es teh manis  26.000"]).lines()[0]
    assert _parse_item_line(line, row_no=1)[1:4] == (4, 6500.0, 26000.0)
