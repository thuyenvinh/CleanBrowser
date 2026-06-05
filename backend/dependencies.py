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
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request, WebSocket, status

from . import database as db
from . import db_auth
from .auth_tokens import decode_session
from .browser_manager import BrowserManager
from .middleware_rls import clear_tenant, set_tenant

logger = logging.getLogger("cloakbrowser.manager")

# Singleton browser manager — shared by all routers.
browser_mgr = BrowserManager()

# Frontend build directory (React production build).
FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"

# Paths that bypass authentication even when AUTH_TOKEN is set. The new
# multi-tenant endpoints either handle auth themselves (signup/login/status)
# or rely on the ``session`` cookie via ``get_current_user`` (me, logout) so
# they must not be gated by the legacy AUTH_TOKEN middleware.
_AUTH_EXEMPT = frozenset(
    {
        "/api/auth/status",
        "/api/auth/login",
        "/api/auth/signup",
        "/api/auth/logout",
        "/api/auth/me",
        "/api/auth/forgot-password",
        "/api/auth/reset-password",
        "/api/auth/verify-email",
        # ``/api/status`` returns global counters (profiles_total) and is NOT
        # public — security review H-04 moved it behind auth. Marketing /
        # status-page traffic continues to use ``/api/status/public``.
        "/api/status/public",
        "/api/billing/plans/public",
    }
)

# Prefix patterns exempt from auth middleware (OAuth callbacks, webhook
# receivers, public file serving). These never require a session — they
# either carry their own auth token in the URL or are public marketing pages.
_AUTH_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/api/auth/oauth/",
    "/api/webhooks/",
    "/api/billing/webhook",
    "/api/billing/vnpay/return",
    "/api/marketplace/install/complete",
)

# Name of the JWT session cookie issued by /api/auth/{signup,login}.
SESSION_COOKIE = "session"


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


# ---------------------------------------------------------------------------
# Multi-tenant auth dependencies (Wave 2).
#
# These read the ``session`` JWT cookie set by /api/auth/{signup,login} and
# resolve it to the current user row from the DB. The legacy ``AUTH_TOKEN``
# middleware in ``main.py`` still runs first when AUTH_TOKEN is set, so these
# dependencies focus purely on identifying the *user* behind a request.
# ---------------------------------------------------------------------------


async def get_optional_user(request: Request) -> dict[str, Any] | None:
    """Return the user dict for the current request, or ``None`` if unauth'd.

    Two auth paths, tried in order:

    1. ``Authorization: Bearer <api_key>`` — programmatic clients (curl,
       Playwright/Puppeteer scripts, CI/CD). The token is looked up via
       :func:`db_auth.get_api_key_by_token`, which also bumps the key's
       ``last_used_at`` as a side effect.
    2. ``session`` cookie — interactive browser session (JWT issued by
       ``/api/auth/{signup,login}``).

    Never raises — callers wanting a 401 should use :func:`get_current_user`.
    """
    # ── Path 1: API key (Authorization: Bearer <token>) ────────────────────
    # We deliberately ignore Bearer tokens that match the legacy AUTH_TOKEN —
    # those are handled by the AuthMiddleware in :mod:`backend.main` and must
    # not be misinterpreted as a per-user API key here.
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        api_token = auth_header[7:].strip()
        if api_token:
            # Same RLS bypass rationale as the JWT path below.
            from .middleware_rls import system_context as _sysctx
            try:
                with _sysctx():
                    key_row = db_auth.get_api_key_by_token(api_token)
            except Exception:
                logger.exception("get_optional_user: api-key lookup failed")
                key_row = None
            if key_row:
                try:
                    with _sysctx():
                        user = db_auth.get_user(key_row["user_id"])
                except Exception:
                    logger.exception(
                        "get_optional_user: db lookup failed for api-key user=%s",
                        key_row.get("user_id"),
                    )
                    user = None
                if user and user.get("status") == "active":
                    request.state.user = user
                    set_tenant(user.get("tenant_id"))
                    return user

    # ── Path 2: JWT session cookie ─────────────────────────────────────────
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        clear_tenant()
        return None
    payload = decode_session(token)
    if not payload:
        clear_tenant()
        return None
    user_id = payload.get("sub")
    if not user_id:
        clear_tenant()
        return None
    # RLS RESTRICTIVE on `users` would block this lookup before any tenant
    # context is pinned. Use system bypass for the identity check; we re-pin
    # the tenant below once we've confirmed the JWT belongs to a real user.
    from .middleware_rls import system_context
    try:
        with system_context():
            user = db_auth.get_user(user_id)
    except Exception:  # DB error: treat as unauth'd, don't 500 the caller
        logger.exception("get_optional_user: db lookup failed for sub=%s", user_id)
        clear_tenant()
        return None
    if not user or user.get("status") != "active":
        clear_tenant()
        return None
    # Sanity-check the tenant id in the token matches the user's tenant — if a
    # user is reassigned tenants (shouldn't happen in v1, but be defensive) the
    # stale token must not grant access.
    if payload.get("tid") and payload["tid"] != user.get("tenant_id"):
        clear_tenant()
        return None
    # Reject tokens issued before the most recent password change
    # (security review M-07). The JWT ``iat`` claim is a unix epoch; we
    # compare it against ``users.password_changed_at`` so resetting a
    # password instantly invalidates every outstanding cookie. Missing
    # ``iat`` (legacy tokens) defaults to "valid" — they'll expire on
    # their own 24h TTL.
    iat = payload.get("iat")
    pwd_changed = user.get("password_changed_at")
    if iat is not None and pwd_changed:
        # ``password_changed_at`` round-trips through ``_row_to_dict`` as an
        # ISO-8601 string. Parse defensively — a corrupt timestamp must not
        # accidentally lock out the entire user base.
        try:
            import datetime as _dt
            if isinstance(pwd_changed, str):
                pwd_changed = _dt.datetime.fromisoformat(pwd_changed)
            pwd_changed_epoch = int(pwd_changed.timestamp())
            if int(iat) < pwd_changed_epoch:
                clear_tenant()
                return None
        except (ValueError, TypeError, AttributeError):
            logger.warning(
                "password_changed_at parse failed for user=%s — allowing session",
                user_id,
            )
    # Expose the user dict on request.state so downstream middleware (notably
    # AuditMiddleware) can attribute actions to the authenticated actor. We
    # only set this when we have a real user — unauthenticated requests leave
    # the attribute unset so middleware can fall back to ``getattr(...)``.
    request.state.user = user
    # Pin the tenant id into a request-scoped ContextVar so that the next
    # ``get_db()`` checkout sets ``app.current_tenant_id`` on its connection,
    # engaging the RLS policies from migration 0009 as defence in depth
    # underneath ``check_role_for_workspace``. See :mod:`backend.middleware_rls`.
    set_tenant(user.get("tenant_id"))
    return user


async def get_current_user(
    user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """Like :func:`get_optional_user` but raises 401 when missing."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def _resolve_workspace_id(request: Request) -> str | None:
    """Extract the workspace context for a request.

    Phase 1 strategy: accept ``X-Workspace-Id`` header or ``workspace_id`` query
    param. Phase 2 will derive it from the resource being acted on (e.g. the
    profile's workspace_id).
    """
    ws = request.headers.get("x-workspace-id")
    if ws:
        return ws
    return request.query_params.get("workspace_id")


# Role hierarchy for RBAC (Phase 1, task O). Numbers ascend with privilege:
# viewer (1) < launcher (2) < editor (3) < admin (4) < owner (5).
ROLE_LEVEL: dict[str, int] = {
    "viewer": 1,
    "launcher": 2,
    "editor": 3,
    "admin": 4,
    "owner": 5,
}


def check_role_for_workspace(
    user: dict[str, Any] | None,
    workspace_id: str | None,
    min_level: int,
) -> str | None:
    """Assert ``user`` has at least ``min_level`` permission in ``workspace_id``.

    Returns the user's role string on success. Behaviour:

    * ``user is None``  → returns ``None`` (legacy / unauthenticated bypass —
      callers that already gated their workspace check on the caller having a
      session will simply skip the role check too).
    * ``workspace_id is None`` → 404 (orphan profile, hidden from authenticated
      users to avoid leaking existence across tenants).
    * No membership → 404 (same leakage concern).
    * Role present but below ``min_level`` → 403 "insufficient role".
    """
    if user is None:
        return None
    if not workspace_id:
        raise HTTPException(status_code=404, detail="Profile not found")
    try:
        role = db_auth.get_member_role(workspace_id, user["id"])
    except Exception:
        logger.exception(
            "check_role_for_workspace: get_member_role failed (ws=%s user=%s)",
            workspace_id,
            user.get("id"),
        )
        raise HTTPException(status_code=500, detail="role lookup failed")
    if role is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    level = ROLE_LEVEL.get(role, 0)
    if level < min_level:
        raise HTTPException(status_code=403, detail="insufficient role")
    return role


def require_role(*allowed: str) -> Callable[..., dict[str, Any]]:
    """Build a dependency that asserts the current user has one of ``allowed``.

    The check is scoped to the workspace identified by ``X-Workspace-Id``
    header / ``workspace_id`` query param. Returns a dict augmented with
    ``current_role`` and ``current_workspace_id`` so handlers can use them.
    """

    if not allowed:
        raise ValueError("require_role() needs at least one role")
    allowed_set = frozenset(allowed)

    async def _dep(
        request: Request,
        user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        workspace_id = _resolve_workspace_id(request)
        if not workspace_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace context required (X-Workspace-Id header)",
            )
        try:
            role = db_auth.get_member_role(workspace_id, user["id"])
        except Exception:
            logger.exception(
                "require_role: get_member_role failed (ws=%s user=%s)",
                workspace_id,
                user.get("id"),
            )
            raise HTTPException(status_code=500, detail="role lookup failed")
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this workspace",
            )
        if role not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {sorted(allowed_set)}",
            )
        return {**user, "current_role": role, "current_workspace_id": workspace_id}

    return _dep


# ---------------------------------------------------------------------------
# Quota enforcement dependency (Wave 5 phase 1 — task JJJ).
#
# The :mod:`backend.quota` module owns the actual check; this thin factory
# adapts it into a FastAPI dependency so router authors can write
# ``Depends(require_quota("create_profile"))`` once the wave-13 wiring task
# arrives. Kept here (rather than inside ``quota.py``) so route authors find
# it next to the existing ``require_role`` factory above — both follow the
# same closure-over-config pattern.
# ---------------------------------------------------------------------------


def require_quota(action: str) -> Callable[..., Any]:
    """Build a dependency that 402s if ``action`` would exceed the tenant's quota.

    Usage::

        @router.post("/profiles", dependencies=[Depends(require_quota("create_profile"))])
        def create_profile(...):
            ...

    The actual check is delegated to :func:`backend.quota.check_quota`; on
    success the resulting :class:`~backend.quota.QuotaCheckResult` is also
    returned so handlers that want the ``current``/``limit`` numbers (e.g.
    to surface "9 of 10 profiles used" in a response header) can bind it
    via ``quota: QuotaCheckResult = Depends(require_quota("create_profile"))``.
    """
    # Lazy import keeps ``dependencies`` importable even if ``quota`` is
    # being edited / not yet on disk during the wave's branch shuffling.
    from . import quota as _quota

    async def _dep(user: dict[str, Any] = Depends(get_current_user)) -> Any:
        result = _quota.check_quota(user["tenant_id"], action)  # type: ignore[arg-type]
        result.raise_if_exceeded()
        return result

    return _dep


# ---------------------------------------------------------------------------
# Email verification gate (H8).
#
# ``get_current_user`` only proves identity — it doesn't care whether the
# email behind the session has been confirmed. That's deliberate: an
# unverified user still needs to read /api/auth/me, resend the verification
# email, and access read-only pages so they understand why their account is
# limited. Sensitive *write* actions, on the other hand, must wait until
# verification completes — otherwise a fresh signup can immediately spam
# invites, mint API keys, or kick off a paid checkout before we've proven the
# email even belongs to them. This dependency is the gate.
# ---------------------------------------------------------------------------


async def require_platform_admin(
    user: dict = Depends(get_current_user),
) -> dict:
    """Gate cross-tenant admin endpoints behind the ``is_platform_admin`` flag.

    Platform admins are minted by ``scripts/seed_admin.py`` or by an
    existing platform admin calling ``POST /api/admin/users/{id}/promote``.
    The flag is checked on every request (no caching) so a demoted user
    loses access at the next call without waiting for their JWT to expire.
    """
    if not user.get("is_platform_admin"):
        # Don't leak the existence of the admin surface to non-admins —
        # respond with the same 404 a non-existent route would give.
        raise HTTPException(status_code=404, detail="Not found")
    return user


async def require_verified_email(user: dict = Depends(get_current_user)) -> dict:
    """Block action if user hasn't verified email.

    Used on sensitive routes: workspace invite, API key creation, billing
    checkout. Users still authenticate normally; they just can't perform
    these actions until they click the link in their verification email.
    """
    if not user.get("email_verified_at"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "email_not_verified",
                "message": "Please verify your email address before performing this action. Check your inbox or click 'Resend verification email' in the banner.",
            },
        )
    return user
