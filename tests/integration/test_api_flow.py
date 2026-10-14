"""Upload -> process -> review -> export -> archive, through the HTTP API."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from openpyxl import load_workbook

from tests.integration.conftest import SAMPLES


def upload(client, session, name, data, engine="rules"):
    r = client.post("/api/v1/documents", headers=session, files=[("files", (name, data, "application/octet-stream"))],
                    data={"engine": engine})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["database"] is True
    assert r.headers["x-content-type-options"] == "nosniff"


def test_session_header_required(client):
    assert client.get("/api/v1/documents").status_code == 401
    assert client.get("/api/v1/documents", headers={"X-DokuData-Session": "short"}).status_code == 401


def test_rejects_files_by_content_not_extension(client, session):
    body = upload(client, session, "nota.pdf", b"this is not a pdf at all")
    assert body["documents"] == []
    assert "tidak didukung" in body["rejected"][0]["reason"]


def test_full_flow(client, session, pdf_bytes):
    body = upload(client, session, "faktur.pdf", pdf_bytes)
    doc_id = body["documents"][0]["id"]
    assert doc_id.startswith("doc_")

    detail = client.get(f"/api/v1/documents/{doc_id}", headers=session).json()
    assert detail["status"] in ("auto_approved", "needs_review"), detail.get("error")
    assert detail["doc_type"] == "invoice"
    gt = next(
        s
        for s in json.loads((SAMPLES / "samples.json").read_text(encoding="utf-8"))
        if s["name"] == "faktur-pdf"
    )["ground_truth"]
    assert detail["data"]["total"] == gt["total"]
    assert detail["result"]["engines"]["ocr"] == "pdf_text"
    assert len(detail["pages"]) == 1

    # Page images are served only through signed URLs.
    page_url = detail["pages"][0]["url"]
    assert client.get(page_url).status_code == 200
    assert client.get(page_url.replace("sig=", "sig=x")).status_code == 403

    # Another session cannot see the document.
    other = {"X-DokuData-Session": "another-session-token-abcdefgh"}
    assert client.get(f"/api/v1/documents/{doc_id}", headers=other).status_code == 404

    # Review with a corrected vendor name.
    values = dict(detail["data"])
    values["vendor_name"] = "PT Koreksi Manual"
    r = client.patch(f"/api/v1/documents/{doc_id}/review", headers=session, json={"data": values})
    assert r.status_code == 200, r.text
    assert r.json()["document"]["status"] == "reviewed"
    assert "vendor_name" in r.json()["changed_fields"]

    # Export to Excel.
    r = client.post("/api/v1/exports", headers=session, json={"document_ids": [doc_id], "format": "xlsx"})
    assert r.status_code == 201, r.text
    dl = client.get(r.json()["download_url"])
    assert dl.status_code == 200
    wb = load_workbook(io.BytesIO(dl.content))
    sheet = wb["Ringkasan"]
    vendor_col = [c.value for c in sheet[4]].index("Vendor")
    assert sheet[5][vendor_col].value == "PT Koreksi Manual"
    assert client.get(f"/api/v1/documents/{doc_id}", headers=session).json()["status"] == "exported"

    # Archive: preview, then ZIP with the patterned name.
    r = client.post("/api/v1/archive/organize", headers=session, json={"document_ids": [doc_id]})
    path = r.json()["items"][0]["path"]
    assert path.startswith("Arsip/") and "PTKoreksiManual" in path
    r = client.post(
        "/api/v1/archive/organize", headers=session, json={"document_ids": [doc_id], "apply": True}
    )
    z = zipfile.ZipFile(io.BytesIO(client.get(r.json()["zip_url"]).content))
    assert z.namelist() == [path]

    # Events stream reports the terminal status and closes.
    ev = client.get(detail["events_url"])
    assert "event: status" in ev.text and "exported" in ev.text

    # Delete removes everything.
    assert client.delete(f"/api/v1/documents/{doc_id}", headers=session).status_code == 204
    assert client.get(f"/api/v1/documents/{doc_id}", headers=session).status_code == 404


def test_review_rejects_invalid_data(client, session, pdf_bytes):
    doc_id = upload(client, session, "f.pdf", pdf_bytes)["documents"][0]["id"]
    values = client.get(f"/api/v1/documents/{doc_id}", headers=session).json()["data"]
    values["issue_date"] = "2999-01-01"
    r = client.patch(f"/api/v1/documents/{doc_id}/review", headers=session, json={"data": values})
    assert r.status_code == 422


def test_unreviewed_documents_are_not_exported_by_default(client, session):
    data = (SAMPLES / "nota-injeksi.jpg").read_bytes()
    doc = upload(client, session, "nota.jpg", data)["documents"][0]
    detail = client.get(f"/api/v1/documents/{doc['id']}", headers=session).json()
    # The injected instruction must force a human review.
    assert detail["status"] == "needs_review"
    assert any("prompt injection" in f for f in detail["result"]["flags"])
    r = client.post("/api/v1/exports", headers=session, json={"document_ids": [doc["id"]], "format": "csv"})
    assert r.status_code == 400
    r = client.post(
        "/api/v1/exports",
        headers=session,
        json={"document_ids": [doc["id"]], "format": "csv", "include_unreviewed": True},
    )
    assert r.status_code == 201


def test_duplicate_upload_is_flagged(client, session, pdf_bytes):
    upload(client, session, "a.pdf", pdf_bytes)
    second = upload(client, session, "b.pdf", pdf_bytes)["documents"][0]["id"]
    detail = client.get(f"/api/v1/documents/{second}", headers=session).json()
    assert detail["status"] == "needs_review"
    assert any(f["rule"] == "duplicate_document" for f in detail["result"]["validation"])


def test_list_filters_and_counts(client, session, pdf_bytes):
    upload(client, session, "x.pdf", pdf_bytes)
    r = client.get("/api/v1/documents", headers=session, params={"doc_type": "invoice"})
    assert r.status_code == 200
    assert r.json()["total"] >= 1
    assert all(d["doc_type"] == "invoice" for d in r.json()["items"])
    assert (
        client.get("/api/v1/documents", headers=session, params={"doc_type": "receipt"}).json()["total"] == 0
    )


def test_demo_samples(client, session):
    samples = client.get("/api/v1/demo/samples").json()
    assert {s["name"] for s in samples} >= {"faktur-pdf", "surat-undangan"}
    assert client.get(samples[0]["thumbnail_url"]).status_code == 200
    r = client.post("/api/v1/demo/samples/faktur-pdf", headers=session)
    assert r.status_code == 201 and r.json()["is_sample"] is True


@pytest.mark.slow
def test_out_of_scope_document_is_rejected(client, session):
    doc = upload(client, session, "surat.jpg", (SAMPLES / "surat-undangan.jpg").read_bytes())["documents"][0]
    detail = client.get(f"/api/v1/documents/{doc['id']}", headers=session).json()
    assert detail["status"] == "rejected"


def test_retention_purges_old_documents(client, session, pdf_bytes):
    from datetime import UTC, datetime, timedelta

    from api.cleanup import purge_expired

    doc_id = upload(client, session, "old.pdf", pdf_bytes)["documents"][0]["id"]
    purge_expired(now=datetime.now(UTC) + timedelta(hours=25))
    assert client.get(f"/api/v1/documents/{doc_id}", headers=session).status_code == 404


def test_evaluation_assets_reject_path_traversal(client):
    assert client.get("/api/v1/evaluation/assets/..%2F..%2Fpyproject.toml").status_code == 404
    assert client.get("/api/v1/evaluation/assets/missing.png").status_code == 404
