"""Retention: delete visitors' uploads after ``retention_hours`` (PRD 16.1)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from api.db.models import Document, Export
from api.db.session import session_scope
from api.settings import get_settings
from api.storage import get_storage

log = logging.getLogger("dokudata.cleanup")


def purge_expired(now: datetime | None = None) -> int:
    s = get_settings()
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=s.retention_hours)
    storage = get_storage()
    removed = 0
    with session_scope() as db:
        docs = db.scalars(select(Document).where(Document.created_at < cutoff)).all()
        for doc in docs:
            storage.delete_prefix(f"{doc.owner}/{doc.id}")
            db.delete(doc)
            removed += 1
        exports = db.scalars(select(Export).where(Export.created_at < cutoff)).all()
        for exp in exports:
            storage.delete(exp.storage_key)
            db.delete(exp)
    if removed:
        log.info("retention: removed %d documents older than %s", removed, cutoff.isoformat())
    return removed


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(f"removed {purge_expired()} documents")
