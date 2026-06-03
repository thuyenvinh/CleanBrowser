"""CloakBrowser Manager — FastAPI application.

Serves the React dashboard (static files) and provides a REST API
for browser profile management with live VNC viewing.

This module wires the FastAPI ``app`` together by including domain routers
from ``backend.routers``. Endpoint implementations live in those routers;
this file only handles app construction, auth middleware, lifespan, and
static file mounting for the SPA build.
"""

from __future__ import annotations

import asyncio  # re-exported for tests that patch ``backend.main.asyncio.*``
import hmac
import logging
import os
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Receive, Scope, Send

from . import automation_scheduler
from . import database as db
from . import overage_worker
from . import proxy_health
from . import status_worker
from . import idle_reaper
from . import trial_expiry_worker
from .dependencies import (
    FRONTEND_DIR,
    _AUTH_EXEMPT,
    _check_websocket_origin,  # re-export for backward compatibility
    _is_https,  # re-export for backward compatibility
    browser_mgr,
)
from .middleware_audit import AuditMiddleware
from .rate_limit import limiter, RateLimitExceeded, _rate_limit_exceeded_handler
from .routers import ai as ai_router
from .routers import auth as auth_router
from .routers import automations as automations_router
from .routers import billing as billing_router
from .routers import cdp as cdp_router
from .routers import clipboard as clipboard_router
from .routers import marketplace as marketplace_router
from .routers import profiles as profiles_router
from .routers import proxies as proxies_router
from .routers import regions as regions_router
from .routers import system as system_router
from .routers import vnc as vnc_router
from .routers import webhooks as webhooks_router
from .routers import workspaces as workspaces_router

# Re-export RFB helpers so existing tests that do
# ``from backend.main import _filter_rfb_client_messages`` keep working.
from .routers.vnc import (  # noqa: F401
    _ALLOWED_ENCODINGS,
    _build_server_cut_text,
    _filter_rfb_client_messages,
    _parse_kasmvnc_clipboard,
    _rewrite_pointer_event,
    _rewrite_set_encodings,
    _rfb_msg_length,
)

logger = logging.getLogger("cloakbrowser.manager")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

# Optional authentication via AUTH_TOKEN env var.
# If not set, all routes are open (local dev). If set, all /api/* routes
# (except /api/auth/* and /api/status) require Bearer token or cookie.
AUTH_TOKEN: str | None = os.environ.get("AUTH_TOKEN") or None


def _check_auth(scope: Scope) -> bool:
    """Check if the request has a valid auth token (header or cookie)."""
    # Check Authorization: Bearer <token> header
    for key, val in scope.get("headers", []):
        if key == b"authorization":
            auth_value = val.decode()
            if auth_value.startswith("Bearer "):
                token = auth_value[7:]
                if token and hmac.compare_digest(token, AUTH_TOKEN):
                    return True
            break

    # Check auth_token cookie (legacy single-token) AND session cookie (JWT)
    for key, val in scope.get("headers", []):
        if key == b"cookie":
            cookies = SimpleCookie()
            cookies.load(val.decode())
            if "auth_token" in cookies:
                cookie_val = cookies["auth_token"].value
                if cookie_val and hmac.compare_digest(cookie_val, AUTH_TOKEN):
                    return True
            # Multi-tenant JWT session — a valid signed token from the
            # email/password flow is just as good as the legacy bearer.
            if "session" in cookies:
                from .auth_tokens import decode_session
                if decode_session(cookies["session"].value) is not None:
                    return True
            break

    # Also accept a JWT in the Authorization header (API keys / SDKs).
    for key, val in scope.get("headers", []):
        if key == b"authorization":
            auth_value = val.decode()
            if auth_value.startswith("Bearer "):
                token = auth_value[7:]
                from .auth_tokens import decode_session
                if decode_session(token) is not None:
                    return True
            break

    return False


class AuthMiddleware:
    """Raw ASGI middleware for optional token auth.

    Uses raw ASGI instead of BaseHTTPMiddleware because the latter
    breaks WebSocket routes (wraps request body, preventing WS upgrade).
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        # Pass through if auth disabled, or non-HTTP/WS scope (e.g. lifespan)
        if not AUTH_TOKEN or scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        # Skip auth for exempt endpoints and non-API paths (static frontend)
        from .dependencies import _AUTH_EXEMPT_PREFIXES
        if (
            path in _AUTH_EXEMPT
            or any(path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES)
            or not path.startswith("/api/")
        ):
            await self.app(scope, receive, send)
            return

        if _check_auth(scope):
            await self.app(scope, receive, send)
            return

        # Reject — unauthenticated
        if scope["type"] == "websocket":
            # ASGI requires receiving websocket.connect before sending close
            await receive()
            await send({"type": "websocket.close", "code": 4401, "reason": "Unauthorized"})
        else:
            response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from . import telemetry as _telemetry
    _telemetry.setup_tracing(app)
    db.init_db()
    await browser_mgr.cleanup_stale()
    browser_mgr._auto_launch_task = asyncio.create_task(browser_mgr.auto_launch_all())
    await proxy_health.start()
    await status_worker.start()
    await automation_scheduler.start()
    await idle_reaper.start()
    await overage_worker.start()
    await trial_expiry_worker.start()
    logger.info("CloakBrowser Manager started")
    yield
    logger.info("Shutting down — stopping all browsers...")
    if browser_mgr._auto_launch_task and not browser_mgr._auto_launch_task.done():
        browser_mgr._auto_launch_task.cancel()
        await asyncio.gather(browser_mgr._auto_launch_task, return_exceptions=True)
    await trial_expiry_worker.stop()
    await overage_worker.stop()
    await idle_reaper.stop()
    await automation_scheduler.stop()
    await status_worker.stop()
    await proxy_health.stop()
    await browser_mgr.cleanup_all()


app = FastAPI(title="CloakBrowser Manager", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# Starlette applies middleware in reverse registration order (last-registered
# is outermost). We want AuthMiddleware to run BEFORE AuditMiddleware so the
# auth dependency has a chance to populate ``request.state.user`` that
# AuditMiddleware reads. Register Audit FIRST so Auth ends up outermost.
app.add_middleware(AuditMiddleware)
app.add_middleware(AuthMiddleware)

# Mount domain routers — order doesn't affect routing, but we list them
# from most specific to least specific for readability.
app.include_router(auth_router.router)
app.include_router(workspaces_router.router)
app.include_router(profiles_router.router)
app.include_router(proxies_router.router)
app.include_router(automations_router.router)
app.include_router(regions_router.router)
app.include_router(vnc_router.router)
app.include_router(cdp_router.router)
app.include_router(clipboard_router.router)
app.include_router(system_router.router)
app.include_router(billing_router.router)
app.include_router(ai_router.router)
app.include_router(marketplace_router.router)
app.include_router(webhooks_router.router)


# ── Static Frontend ───────────────────────────────────────────────────────────

# Serve React build. Must be AFTER API routes so /api/* isn't caught by the SPA.
if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve React SPA — all non-API routes return index.html."""
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        file_path = FRONTEND_DIR / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")
