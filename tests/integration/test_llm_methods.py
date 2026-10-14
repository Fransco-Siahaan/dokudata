"""Methods B and C through the API, with a fake Claude client (no network, no cost)."""

from __future__ import annotations

import json

import pytest

from pipeline.llm import FakeLLMClient
from tests.integration.conftest import SAMPLES
from tests.integration.test_api_flow import upload


def ground_truth(name: str) -> dict:
    return next(
        s for s in json.loads((SAMPLES / "samples.json").read_text(encoding="utf-8")) if s["name"] == name
    )["ground_truth"]


def llm_answer(gt: dict) -> dict:
    def f(v):
        return {"value": v, "source_text": None}

    return {
        "document_type": gt["document_type"],
        **{
            k: f(gt.get(k))
            for k in (
                "vendor_name",
                "vendor_tax_id",
                "document_number",
                "issue_date",
                "due_date",
                "payment_method",
                "subtotal",
                "discount",
                "tax_amount",
                "total",
            )
        },  # fmt: skip
        "currency": f("IDR"),
        "line_items": [dict(li) for li in gt["line_items"]],
        "suspicious_instructions": False,
    }


@pytest.fixture
def llm_on(monkeypatch):
    from api import worker
    from api.settings import Settings

    gt = ground_truth("faktur-pdf")
    fake = FakeLLMClient(lambda _s, _c: llm_answer(gt))
    monkeypatch.setattr(Settings, "llm_configured", property(lambda self: True))
    monkeypatch.setattr(worker, "llm_client", lambda: fake)
    monkeypatch.setattr(worker, "_pipelines", {})
    return fake, gt


def test_llm_methods_are_refused_when_not_configured(client, session, pdf_bytes, monkeypatch):
    from api.settings import Settings

    monkeypatch.setattr(Settings, "llm_configured", property(lambda self: False))
    r = client.post("/api/v1/documents", headers=session, files=[("files", ("f.pdf", pdf_bytes, "application/pdf"))],
                    data={"engine": "llm_ocr"})  # fmt: skip
    assert r.status_code == 400 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    assert (
        client.post("/api/v1/demo/samples/faktur-pdf?engine=llm_vision", headers=session).status_code == 400
    )
    assert client.get("/api/v1/health").json()["llm_configured"] is False


@pytest.mark.parametrize("engine", ["llm_ocr", "llm_vision"])
def test_llm_methods_end_to_end(client, session, pdf_bytes, llm_on, engine):
    fake, gt = llm_on
    doc_id = upload(client, session, "faktur.pdf", pdf_bytes, engine=engine)["documents"][0]["id"]
    detail = client.get(f"/api/v1/documents/{doc_id}", headers=session).json()
    assert detail["engine"] == engine
    assert detail["result"]["engines"]["extractor"] == engine
    assert detail["result"]["engines"]["cross_check"] == "rules"  # method A double-checks the LLM
    assert detail["data"]["total"] == gt["total"]
    assert detail["status"] in ("auto_approved", "needs_review")
    sent = fake.calls[-1]["content"]
    assert sent[0]["type"] == ("text" if engine == "llm_ocr" else "image")
    assert client.get("/api/v1/health").json()["llm_configured"] is True


def test_reprocess_switches_engine(client, session, pdf_bytes, llm_on):
    doc_id = upload(client, session, "faktur.pdf", pdf_bytes)["documents"][0]["id"]
    r = client.post(f"/api/v1/documents/{doc_id}/reprocess", headers=session, json={"engine": "llm_ocr"})
    assert r.status_code == 200
    detail = client.get(f"/api/v1/documents/{doc_id}", headers=session).json()
    assert detail["result"]["engines"]["extractor"] == "llm_ocr"
