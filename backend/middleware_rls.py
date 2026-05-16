"""Request-scoped tenant context for Postgres row-level security.

ARCHITECTURE §2.2 prescribes ``tenant_id = current_setting('app.tenant_id')``
as a defence-in-depth filter underneath the application-layer
``check_role_for_workspace`` gate. This module owns the *propagation* half
of that scheme: an asyncio-safe :class:`contextvars.ContextVar` that
``backend.dependencies.get_optional_user`` writes when it resolves a session
JWT, and that :func:`backend.database.get_db` reads to set the GUC
``app.current_tenant_id`` on the connection it just checked out of the pool.

Why a ContextVar and not an ASGI middleware that wraps the request?

* The tenant id only becomes known *after* the session cookie has been
  decoded and the user row has been loaded — work that already happens in
  ``get_optional_user``. Splitting that across a middleware would mean
  parsing the JWT twice (or threading state through ``request.state``).
* ContextVars are the canonical FastAPI-friendly mechanism for
  request-scoped values: each task/connection inherits the parent task's
  copy, and writes don't leak across requests because Starlette runs each
  request in its own task.

Phase 1 design notes:

* The RLS policies created by migration ``0009_add_rls`` are *permissive*:
  if ``app.current_tenant_id`` is empty/unset the row is allowed through.
  Tests, scripts, and the legacy ``AUTH_TOKEN`` bearer flow therefore keep
  working without any plumbing changes; only authenticated multi-tenant
  requests (which already populate ``request.state.user``) actually engage
  the filter.
* When the migration is rolled back the helpers below silently become
  no-ops — they just write a GUC nobody reads.
"""

from __future__ import annotations

from contextvars import ContextVar

# Default is ``None`` (i.e. "no tenant pinned"). An empty string is treated
# identically downstream — both mean "let the permissive policy fall through".
_current_tenant: ContextVar[str | None] = ContextVar(
    "current_tenant_id", default=None
)


def set_tenant(tenant_id: str | None) -> None:
    """Pin the current request's tenant id for RLS filtering.

    Called by :func:`backend.dependencies.get_optional_user` once the user
    row has been loaded. Passing ``None`` or an empty string clears the
    binding (equivalent to :func:`clear_tenant`).
    """
    _current_tenant.set(tenant_id or None)


def clear_tenant() -> None:
    """Remove any pinned tenant id (unauthenticated requests, logouts)."""
    _current_tenant.set(None)


def get_current_tenant() -> str | None:
    """Return the tenant id pinned for the current request, if any.

    Read by :func:`backend.database.get_db` *after* it has checked a
    connection out of the pool, so the GUC ``app.current_tenant_id`` is set
    before any user-driven query runs.
    """
    return _current_tenant.get()
