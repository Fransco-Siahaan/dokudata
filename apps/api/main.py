"""DokuData API.

uvicorn api.main:app --app-dir apps --reload
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import __version__
from api.cleanup import purge_expired
from api.db.session import init_db
from api.routers import documents, exports, misc
from api.security import SecurityHeadersMiddleware
from api.settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("dokudata.api")


async def _retention_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(purge_expired)
        except Exception:
            log.exception("retention job failed")
        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    task = asyncio.create_task(_retention_loop()) if get_settings().env != "test" else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="DokuData API",
        version=__version__,
        description="Dokumen administrasi menjadi data terstruktur: OCR, klasifikasi, ekstraksi, validasi, tinjauan.",
        lifespan=lifespan,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["X-DokuData-Session", "Content-Type"],
    )
    for r in (documents.router, exports.router, misc.router):
        app.include_router(r, prefix="/api/v1")
    return app


app = create_app()
