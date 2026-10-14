from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="dokudata-test-"))
os.environ.update({
    "DOKUDATA_ENV": "test",
    "DOKUDATA_DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
    "DOKUDATA_STORAGE_DIR": str(_TMP / "storage"),
    "DOKUDATA_QUEUE_MODE": "inline",
    "DOKUDATA_SECRET_KEY": "test-secret",
    "DOKUDATA_RETENTION_HOURS": "24",
})  # fmt: skip

SAMPLES = Path(__file__).resolve().parents[2] / "apps" / "api" / "samples"


@pytest.fixture(scope="session")
def app():
    from api.main import app as fastapi_app

    return fastapi_app


@pytest.fixture
def client(app, monkeypatch):
    from fastapi.testclient import TestClient

    from api import worker
    from api.routers import documents, misc

    # Run jobs synchronously so tests can assert on the finished document.
    monkeypatch.setattr(documents, "enqueue_document", worker.process_document)
    monkeypatch.setattr(misc, "enqueue_document", worker.process_document)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def session() -> dict[str, str]:
    return {"X-DokuData-Session": secrets.token_urlsafe(24)}


@pytest.fixture
def pdf_bytes() -> bytes:
    return (SAMPLES / "faktur-pdf.pdf").read_bytes()
