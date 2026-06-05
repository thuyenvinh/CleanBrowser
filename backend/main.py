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


def _assert_production_safety() -> None:
    """Fail-closed boot guard: refuse to start with insecure defaults in prod.

    Active only when ``APP_ENV=production``. Catches the deployment foot-guns
    that the security review flagged as Critical/High:
      * empty AUTH_TOKEN + no JWT_SECRET → unauthenticated by default
      * COOKIE_SECURE off → session cookie sent over plaintext
      * rate-limit storage stuck on in-process memory across replicas
    """
    if os.environ.get("APP_ENV", "").lower() != "production":
        return

    errors: list[str] = []
    if not (os.environ.get("AUTH_TOKEN") or os.environ.get("JWT_SECRET")):
        errors.append(
            "Neither AUTH_TOKEN nor JWT_SECRET is set. At least one must be "
            "configured in production — running without an auth secret leaves "
            "every /api/* endpoint exposed."
        )
    if not os.environ.get("JWT_SECRET"):
        errors.append(
            "JWT_SECRET is not set. The ephemeral per-process fallback "
            "invalidates sessions on every restart and breaks multi-replica "
            "deployments — set JWT_SECRET in production."
        )
    if os.environ.get("COOKIE_SECURE", "false").lower() != "true":
        errors.append(
            "COOKIE_SECURE is not 'true'. Session cookies will be issued "
            "without the Secure flag — set COOKIE_SECURE=true in production."
        )
    storage_uri = os.environ.get("RATE_LIMIT_STORAGE_URI", "memory://")
    if storage_uri.startswith("memory://"):
        errors.append(
            "RATE_LIMIT_STORAGE_URI is 'memory://'. Per-process rate limits "
            "are bypassable across replicas — point this at Redis "
            "(redis://host:6379) in production."
        )
    if errors:
        bullets = "\n  - ".join(errors)
        raise RuntimeError(
            f"Refusing to start: insecure production configuration.\n  - {bullets}"
        )


_assert_production_safety()


def _check_auth(scope: Scope) -> bool:
    """Check if the request has a valid auth token (header or cookie)."""
    # Defensive guard: callers must short-circuit when AUTH_TOKEN is None,
    # but if they don't, hmac.compare_digest would raise on a None operand.
    if AUTH_TOKEN is None:
        return False
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


_STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Endpoints that need to accept cross-origin POSTs from external providers
# (Stripe, VNPay, OAuth IdPs, integrations posting to public webhooks).
# Anything not on this prefix list is required to be same-origin when
# making a state-changing request — defends against CSRF in case the
# session cookie's SameSite=Lax isn't enough (e.g. a reverse proxy that
# adds a permissive ``Access-Control-Allow-Origin`` upstream).
_CSRF_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/billing/webhook",
    "/api/billing/vnpay/return",
    "/api/webhooks/",
    "/api/auth/oauth/",
    "/api/marketplace/install/complete",
)


class CsrfOriginMiddleware:
    """Defence-in-depth Origin/Referer check for state-changing requests.

    SameSite=Lax on the session cookie already blocks cross-site POST
    submissions, but two failure modes bypass it: (a) a reverse proxy in
    front of FastAPI advertises ``Access-Control-Allow-Origin: *`` and
    leaves preflight to the app, (b) an attacker hosts a same-origin
    payload via subdomain takeover. Reject state-changing requests whose
    Origin / Referer doesn't match the Host header.

    Security review H-03 / L-05.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    @staticmethod
    def _header(scope: Scope, name: bytes) -> str | None:
        for key, val in scope.get("headers", []):
            if key == name:
                return val.decode("latin-1")
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        method = scope.get("method", "GET").upper()
        if method not in _STATE_CHANGING_METHODS:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return
        if any(path.startswith(p) for p in _CSRF_EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return

        origin = self._header(scope, b"origin")
        referer = self._header(scope, b"referer")
        host = self._header(scope, b"host") or ""
        # ``Origin: null`` is sent by browsers for opaque sources (sandboxed
        # iframes, file://, redirects, Playwright APIRequestContext). For
        # CSRF purposes a "null" claim is no claim — treat it like missing.
        if origin == "null":
            origin = None
        if not origin and not referer:
            # Non-browser clients (curl, SDKs, server-to-server) don't send
            # Origin / Referer; cookies aren't auto-attached either, so the
            # CSRF threat doesn't apply. Let the auth layer below decide.
            await self.app(scope, receive, send)
            return

        from urllib.parse import urlparse

        def _host_of(value: str | None) -> str:
            if not value:
                return ""
            try:
                parsed = urlparse(value)
            except ValueError:
                return ""
            netloc = parsed.netloc or parsed.path
            return netloc.split("@")[-1]  # strip user:pass@ if present

        candidate = _host_of(origin) or _host_of(referer)
        # Normalise default-port suffixes (":80"/":443") on both sides.
        def _strip_default_port(value: str) -> str:
            for suffix in (":80", ":443"):
                if value.endswith(suffix):
                    return value[: -len(suffix)]
            return value

        if _strip_default_port(candidate) != _strip_default_port(host):
            response = JSONResponse(
                {"detail": "Cross-origin request rejected"}, status_code=403
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


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
# is outermost). Order we want at runtime (outer → inner):
#   CsrfOriginMiddleware  → reject cross-origin POST/PUT/DELETE first
#   AuthMiddleware        → legacy AUTH_TOKEN / JWT bearer/cookie check
#   AuditMiddleware       → reads request.state.user, must run last
# Registration order is the reverse of the above.
app.add_middleware(AuditMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(CsrfOriginMiddleware)

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

    # Extensions the SPA root is allowed to serve directly (icons, manifest,
    # favicon, fonts, vite static metadata). Everything else falls through
    # to index.html so the React router can handle the route — and
    # importantly, so a traversal payload pointing at /etc/passwd or any
    # other server-side file gets a harmless SPA shell instead.
    _SPA_SERVE_EXTS = frozenset({
        ".html", ".js", ".css", ".map", ".json", ".txt", ".xml",
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
    })
    _FRONTEND_ROOT = FRONTEND_DIR.resolve()

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve React SPA — all non-API routes return index.html.

        Defends against path traversal (security review finding C-03) by
        resolving the requested path and verifying it stays inside the
        frontend build directory before calling ``FileResponse``. Anything
        suspicious (escape, non-whitelisted extension) silently falls back
        to ``index.html`` so the SPA can handle the route.
        """
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        if not full_path:
            return FileResponse(_FRONTEND_ROOT / "index.html")
        try:
            candidate = (_FRONTEND_ROOT / full_path).resolve()
        except (OSError, ValueError):
            return FileResponse(_FRONTEND_ROOT / "index.html")
        # Containment check: resolved path must be inside the frontend dir.
        try:
            candidate.relative_to(_FRONTEND_ROOT)
        except ValueError:
            return FileResponse(_FRONTEND_ROOT / "index.html")
        if candidate.suffix.lower() not in _SPA_SERVE_EXTS:
            return FileResponse(_FRONTEND_ROOT / "index.html")
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_ROOT / "index.html")
