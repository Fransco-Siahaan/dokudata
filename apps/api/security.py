"""Request-level security: anonymous session ownership, signed URLs, rate limits, headers (PRD 16.2).

The public demo has no accounts. Each browser creates a random session token
and sends it as ``X-DokuData-Session``; the server stores only its hash as the
owner of every document, so visitors never see each other's files. Image tags
and downloads cannot send headers, so those use short-lived HMAC-signed URLs.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlencode

from fastapi import Header, HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from api.settings import get_settings

TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{24,128}$")


def owner_of(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:40]


def require_owner(x_dokudata_session: str | None = Header(default=None)) -> str:
    if not x_dokudata_session or not TOKEN_RE.match(x_dokudata_session):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Header X-DokuData-Session tidak ada atau tidak valid"
        )
    return owner_of(x_dokudata_session)


def _sig(path: str, exp: int) -> str:
    key = get_settings().secret_key.encode()
    mac = hmac.new(key, f"{path}|{exp}".encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac[:18]).decode().rstrip("=")


def signed_url(path: str, ttl: int | None = None) -> str:
    exp = int(time.time()) + (ttl or get_settings().signed_url_ttl_s)
    return f"{path}?{urlencode({'exp': exp, 'sig': _sig(path, exp)})}"


def verify_signature(request: Request) -> None:
    try:
        exp = int(request.query_params.get("exp", "0"))
    except ValueError:
        exp = 0
    sig = request.query_params.get("sig", "")
    if exp < time.time() or not hmac.compare_digest(sig, _sig(request.url.path, exp)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tautan tidak valid atau kedaluwarsa")


class RateLimiter:
    """Sliding-window limit per key. In-process; with several API replicas use a Redis-backed limiter."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float, cost: int = 1) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) + cost > limit:
                retry = int(window_s - (now - q[0])) + 1 if q else int(window_s)
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "Terlalu banyak permintaan, coba lagi nanti",
                    headers={"Retry-After": str(retry)},
                )
            q.extend([now] * cost)


rate_limiter = RateLimiter()


def client_ip(request: Request) -> str:
    # Behind the demo's reverse proxy the client address arrives in X-Forwarded-For.
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
            response.headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
        return response
