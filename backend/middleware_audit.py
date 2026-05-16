"""HTTP middleware that emits an audit row for mutation requests.

Phase 1 wave-2 scaffolding. The class is defined here but NOT yet wired into
``main.py`` — that happens in wave 3 once the auth dependency (which sets
``request.state.user``) lands. Until then this file exists purely so the wire-
up commit can be a one-liner.

What it does:
    * Captures path, method, client IP, and User-Agent on the way in.
    * On the way out, if the request was a "interesting" mutation
      (``POST``/``PUT``/``PATCH``/``DELETE`` AND status < 400 AND path matches
      one of the watched prefixes), it fires
      :func:`backend.db_audit.write` describing the action.
    * Action name is inferred from ``(method, path)`` via a small lookup
      table (see :data:`_ACTION_MAP`). Unknown paths get a generic
      ``<resource>.<verb>`` form so we still record *something*.
    * ``actor_user_id`` / ``tenant_id`` are read from ``request.state.user``
      if the auth dependency set it; otherwise ``None`` (e.g. signup, failed
      login attempts).

Explicitly skipped:
    * Any GET (too noisy — read-only requests are observable via access logs).
    * ``/api/status``, ``/api/auth/me`` — health/whoami polling, no audit
      value.
    * Anything not under ``/api/`` — static assets, frontend, websockets.
"""

from __future__ import annotations

import re
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from . import db_audit


# ---------------------------------------------------------------------------
# Path → action mapping
# ---------------------------------------------------------------------------

# Exact-match table for endpoints where the action name is well-known. The
# value is keyed by HTTP method; if the method isn't listed, we fall back to
# the generic inference below.
_EXACT_MAP: dict[str, dict[str, str]] = {
    "/api/auth/signup": {"POST": "user.signup"},
    "/api/auth/login": {"POST": "user.login"},
    "/api/auth/logout": {"POST": "user.logout"},
    "/api/auth/refresh": {"POST": "user.refresh_token"},
    "/api/auth/password": {"POST": "user.password_change", "PUT": "user.password_change"},
    "/api/profiles": {"POST": "profile.create"},
    "/api/workspaces": {"POST": "workspace.create"},
    "/api/api-keys": {"POST": "api_key.create"},
}

# Patterns whose action follows a stable ``<resource>.<verb>`` rule. Order
# matters — first match wins.
_PATTERN_MAP: list[tuple[re.Pattern[str], dict[str, str]]] = [
    (
        re.compile(r"^/api/profiles/[^/]+/launch/?$"),
        {"POST": "profile.launch"},
    ),
    (
        re.compile(r"^/api/profiles/[^/]+/stop/?$"),
        {"POST": "profile.stop"},
    ),
    (
        re.compile(r"^/api/profiles/[^/]+/?$"),
        {"PUT": "profile.update", "PATCH": "profile.update", "DELETE": "profile.delete"},
    ),
    (
        re.compile(r"^/api/workspaces/[^/]+/members/?$"),
        {"POST": "workspace.invite", "DELETE": "workspace.remove_member"},
    ),
    (
        re.compile(r"^/api/workspaces/[^/]+/?$"),
        {"PUT": "workspace.update", "PATCH": "workspace.update", "DELETE": "workspace.delete"},
    ),
    (
        re.compile(r"^/api/api-keys/[^/]+/?$"),
        {"DELETE": "api_key.revoke"},
    ),
]

# Anything matching one of these prefixes is a candidate for auditing. Paths
# outside the list are ignored entirely.
_WATCHED_PREFIXES: tuple[str, ...] = (
    "/api/auth/",
    "/api/profiles",
    "/api/workspaces",
    "/api/admin/",
    "/api/api-keys",
)

# Paths we never audit even though they live under a watched prefix.
_SKIP_PATHS: frozenset[str] = frozenset(
    {
        "/api/status",
        "/api/auth/me",
    }
)

_AUDITED_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# ---------------------------------------------------------------------------
# Resolution helpers
# ---------------------------------------------------------------------------


def _resolve_action(method: str, path: str) -> str | None:
    """Return the audit action name for ``(method, path)``, or ``None``.

    ``None`` means "do not audit" — either the path isn't recognised or the
    method isn't in the map for that path.
    """
    exact = _EXACT_MAP.get(path)
    if exact and method in exact:
        return exact[method]

    for pattern, methods in _PATTERN_MAP:
        if pattern.match(path):
            if method in methods:
                return methods[method]
            return None  # path matched but method not interesting

    return None


def _client_ip(request: Request) -> str | None:
    # Honour ``X-Forwarded-For`` (first hop) when the API sits behind a proxy.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",", 1)[0].strip() or None
    client = request.client
    return client.host if client else None


def _actor_info(request: Request) -> tuple[str | None, str | None]:
    """Pull ``(tenant_id, actor_user_id)`` from ``request.state.user`` if set.

    The auth dependency in wave 3 will populate ``request.state.user`` with a
    dict-like object exposing ``tenant_id`` and ``id``. Until then, this
    returns ``(None, None)`` for every request.
    """
    user: Any = getattr(request.state, "user", None)
    if not user:
        return None, None
    # Support both attribute and mapping access so we don't pin a shape.
    tenant_id = (
        getattr(user, "tenant_id", None)
        if not isinstance(user, dict)
        else user.get("tenant_id")
    )
    actor_id = (
        getattr(user, "id", None)
        if not isinstance(user, dict)
        else user.get("id")
    )
    return (
        str(tenant_id) if tenant_id else None,
        str(actor_id) if actor_id else None,
    )


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class AuditMiddleware(BaseHTTPMiddleware):
    """Write an ``audit_logs`` row for every successful mutation request.

    Failures (status >= 400) are *not* audited here on purpose — login
    failures, permission denials etc. are recorded explicitly by the auth
    router so they include richer context (e.g. *why* it failed). The
    middleware handles the happy-path bulk.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        method = request.method.upper()
        path = request.url.path

        # Cheap early-outs before doing any work.
        skip = (
            method not in _AUDITED_METHODS
            or path in _SKIP_PATHS
            or not any(path.startswith(p) for p in _WATCHED_PREFIXES)
        )

        if skip:
            return await call_next(request)

        # Capture request-side context now: by the time the response comes
        # back, the request body has been consumed and headers may be gone.
        ip = _client_ip(request)
        user_agent = request.headers.get("user-agent")

        response: Response = await call_next(request)

        if response.status_code >= 400:
            return response

        action = _resolve_action(method, path)
        if action is None:
            return response

        tenant_id, actor_user_id = _actor_info(request)

        # Fire-and-forget — ``db_audit.write`` is documented as never raising.
        db_audit.write(
            action=action,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            ip=ip,
            user_agent=user_agent,
            status="success",
            payload={
                "method": method,
                "path": path,
                "status_code": response.status_code,
            },
        )

        return response
