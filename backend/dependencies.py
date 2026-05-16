"""Shared dependencies and singletons for the FastAPI app.

This module hosts pieces that need to be shared across router modules:
- The singleton ``BrowserManager`` instance used by every endpoint.
- Helpers that don't depend on auth (``_is_https``, ``_check_websocket_origin``).
- The frontend build path.

Auth-related globals (``AUTH_TOKEN``, ``_check_auth``, ``AuthMiddleware``) live
in ``backend.main`` so that tests can monkeypatch them via ``main.AUTH_TOKEN``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Request, WebSocket

from . import database as db
from .browser_manager import BrowserManager

logger = logging.getLogger("cloakbrowser.manager")

# Singleton browser manager — shared by all routers.
browser_mgr = BrowserManager()

# Frontend build directory (React production build).
FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"

# Paths that bypass authentication even when AUTH_TOKEN is set.
_AUTH_EXEMPT = frozenset({"/api/auth/status", "/api/auth/login", "/api/status"})


def get_browser_manager() -> BrowserManager:
    """FastAPI dependency returning the singleton BrowserManager."""
    return browser_mgr


def get_db():
    """FastAPI dependency exposing the database module."""
    return db


def _is_https(request: Request) -> bool:
    """Check if the original client connection was HTTPS (via reverse proxy header)."""
    proto = request.headers.get("x-forwarded-proto", "")
    return "https" in proto


async def _check_websocket_origin(websocket: WebSocket) -> bool:
    """Reject cross-origin WebSocket connections (CSWSH protection).

    Browsers always send an Origin header on WebSocket upgrades.
    Non-browser clients (Playwright, curl) typically don't — those are allowed.
    If Origin is present, its host must match the request Host header.
    """
    origin = None
    host = None
    for key, val in websocket.scope.get("headers", []):
        if key == b"origin":
            origin = val.decode("latin-1")
        elif key == b"host":
            host = val.decode("latin-1")

    # No Origin header → non-browser client (Playwright, Puppeteer) → allow
    if not origin:
        return True

    # Parse origin to extract host:port
    try:
        parsed = urlparse(origin)
        origin_host = parsed.hostname or ""
        origin_port = parsed.port
    except ValueError:
        logger.warning("WebSocket origin malformed: %s", origin)
        await websocket.close(code=4403, reason="Origin not allowed")
        return False
    # Build origin netloc (host:port or just host if default port)
    if origin_port and origin_port not in (80, 443):
        origin_netloc = f"{origin_host}:{origin_port}"
    else:
        origin_netloc = origin_host

    if not host:
        return True  # no Host header to compare against

    # Strip default port from Host too (some proxies send "example.com:443")
    host_normalized = host
    if host.endswith(":80") or host.endswith(":443"):
        host_normalized = host.rsplit(":", 1)[0]

    if origin_netloc == host_normalized:
        return True

    logger.warning("WebSocket origin mismatch: origin=%s host=%s", origin, host)
    await websocket.close(code=4403, reason="Origin not allowed")
    return False
