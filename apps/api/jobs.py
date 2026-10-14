"""Job queue: a thread pool in development, RQ + Redis in Docker (separate worker containers)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from api.settings import get_settings

log = logging.getLogger("dokudata.queue")


@lru_cache
def _pool() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=get_settings().inline_workers, thread_name_prefix="dokudata-worker")


@lru_cache
def _rq_queue():
    from redis import Redis
    from rq import Queue

    return Queue("documents", connection=Redis.from_url(get_settings().redis_url))


def enqueue_document(document_id: str) -> None:
    settings = get_settings()
    if settings.queue_mode == "rq":
        from rq import Retry

        _rq_queue().enqueue(
            "api.worker.process_document",
            document_id,
            job_timeout=300,
            retry=Retry(max=2, interval=[10, 30]),
            failure_ttl=86400,
        )
        return
    from api.worker import process_document

    def run() -> None:
        try:
            process_document(document_id)
        except Exception:  # process_document records the failure on the document
            log.exception("inline job failed for %s", document_id)

    _pool().submit(run)


def queue_ping() -> bool:
    if get_settings().queue_mode != "rq":
        return True
    try:
        return bool(_rq_queue().connection.ping())
    except Exception:
        return False
