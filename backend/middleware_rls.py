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

* Migration ``0009_add_rls`` originally installed *permissive* policies:
  if ``app.current_tenant_id`` was empty/unset the row was allowed
  through. That was the safe boot-strap default while routers were being
  wired up.
* Migration ``0012_rls_restrictive`` flipped the same policies to
  *restrictive*: an empty GUC now denies every row, and callers without a
  user context (background workers, conftest truncate, ad-hoc scripts)
  must opt into :func:`system_context` to be allowed through. The
  authenticated request path is unchanged — ``get_optional_user`` still
  writes the tenant id into the ContextVar that :func:`backend.database.get_db`
  reads.
* When the migration is rolled back the helpers below silently become
  no-ops — they just write a GUC nobody reads.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

# Default is ``None`` (i.e. "no tenant pinned"). An empty string is treated
# identically downstream — under the permissive 0009 policy both meant "let
# the fall-through allow every row"; under the restrictive 0012 policy both
# now mean "deny every row unless the caller explicitly opts into
# :func:`system_context`".
_current_tenant: ContextVar[str | None] = ContextVar(
    "current_tenant_id", default=None
)

# Sentinel value recognised by the restrictive RLS policies installed by
# migration ``0012_rls_restrictive`` as "bypass tenant filtering". Mirrors
# ``SYSTEM_GUC_VALUE`` in that migration — keep the two in sync.
#
# Why a magic string rather than e.g. the NIL UUID? Two reasons:
#   * a ``tenant_id::text`` comparison can never accidentally match (no UUID
#     column ever serialises to ``__system__``), so the bypass cannot leak
#     into a row-level filter even if mis-handled by a future policy edit;
#   * it reads in a Postgres dump as obviously-not-a-real-tenant, which
#     matters when grepping ``pg_stat_activity`` or ``pg_settings`` during
#     an incident.
SYSTEM_TENANT_ID = "__system__"


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


@contextmanager
def system_context() -> Iterator[None]:
    """Run a block with RLS tenant filtering disabled.

    Pins the request-scoped ContextVar to :data:`SYSTEM_TENANT_ID` for the
    duration of the ``with`` block; the restrictive policies installed by
    migration ``0012_rls_restrictive`` recognise that sentinel as "bypass"
    and allow every row through. On exit (whether normal or via exception)
    the previous value is restored exactly via :class:`contextvars.Token`,
    so nesting under an authenticated request is safe — the outer tenant
    binding comes back the moment control leaves the block.

    Intended callers (none of which carry user context):

    * background workers — :mod:`backend.proxy_health`,
      :mod:`backend.automation_scheduler`;
    * the test conftest truncate fixture
      (:mod:`backend.tests.conftest`);
    * ad-hoc maintenance scripts (e.g. ``migrate_sqlite_to_postgres.py``).

    Routers / per-user code paths must NEVER use this helper — they have a
    real tenant id from ``get_optional_user`` and should rely on it. Using
    ``system_context`` from a request handler would silently re-enable the
    cross-tenant view the restrictive policy was added to forbid.
    """
    token = _current_tenant.set(SYSTEM_TENANT_ID)
    try:
        yield
    finally:
        _current_tenant.reset(token)
