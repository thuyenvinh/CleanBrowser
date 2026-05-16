"""Marketplace data layer.

Public catalog + per-workspace install ledger for the automation app
marketplace introduced by migration ``0018_add_marketplace``. Same style
as :mod:`backend.db_automation` / :mod:`backend.db_proxy`: synchronous
psycopg2 on top of :func:`backend.database.get_db`, returning plain
``dict`` rows (``RealDictCursor``), UUIDs / datetimes stringified for
JSON serialisation.

Phase 6 phase 1 scope:

* Public browse (anonymous OK) + per-app fetch.
* Install: idempotent on ``(workspace_id, app_id)`` via ``ON CONFLICT
  DO NOTHING``. The HTTP layer handles cloning the bundle into
  ``automations`` / ``automation_versions`` before recording the install
  row — keeping the cross-table choreography in the router lets this
  module stay focused on the two marketplace tables.
* Uninstall: delete the install row and decrement ``install_count``.

Revenue share, ratings, paid apps, and creator self-publish are
deliberately out of scope and have no schema columns yet.

See ``docs/ARCHITECTURE`` §2.6.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

import psycopg2.extras

from .database import get_db


# ---------------------------------------------------------------------------
# Helpers (mirrored from db_automation for consistency)
# ---------------------------------------------------------------------------


def _safe_uuid(value: Any) -> bool:
    """Return ``True`` iff ``value`` parses as a UUID.

    Short-circuits lookups on garbage input so we never round-trip an
    obviously invalid id to Postgres (which would just raise a DataError).
    """
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    """Normalise a psycopg2 RealDict row for JSON serialisation.

    Stringifies UUIDs / datetimes (parity with :mod:`db_auth` and
    :mod:`db_proxy`). JSONB and TEXT[] columns come back as native python
    types already, so no extra handling needed.
    """
    if row is None:
        return None
    out = dict(row)
    for key, val in list(out.items()):
        if isinstance(val, uuid.UUID):
            out[key] = str(val)
        elif isinstance(val, datetime.datetime):
            out[key] = val.isoformat()
    return out


# Columns returned by the list endpoint. ``dsl_json`` / ``script_code`` are
# deliberately omitted from list to keep the payload light — clients fetch
# the full row via :func:`get_app` when they're ready to install.
_LIST_COLUMNS: str = (
    "id, slug, name, description, long_description, icon_url, category, "
    "kind, version, creator_name, creator_url, install_count, "
    "is_official, is_public, required_permissions, created_at, updated_at"
)


# ---------------------------------------------------------------------------
# marketplace_apps — read paths
# ---------------------------------------------------------------------------


def list_public_apps(
    category: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Return public marketplace apps, most-installed first.

    ``category`` filter is exact match (None → all categories). Hits the
    ``ix_marketplace_apps_install_count`` partial index for the ordering
    so popularity sort stays O(public-rows). DSL / script payload is
    omitted to keep the listing payload small.
    """
    where_sql = "WHERE is_public = true"
    params: list[Any] = []
    if category is not None:
        where_sql += " AND category = %s"
        params.append(category)
    params.append(int(limit))

    sql = (
        f"SELECT {_LIST_COLUMNS} FROM marketplace_apps "
        f"{where_sql} "
        f"ORDER BY install_count DESC, name ASC "
        f"LIMIT %s"
    )
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


def get_app(app_id: str) -> dict[str, Any] | None:
    """Fetch a single app by id, including the full DSL / script payload.

    Returns ``None`` for unknown / malformed ids — never raises, callers
    map None → 404 themselves. Includes private (``is_public=false``) rows;
    the HTTP layer is responsible for the visibility check.
    """
    if not _safe_uuid(app_id):
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM marketplace_apps WHERE id = %s", (app_id,)
            )
            return _row_to_dict(cur.fetchone())


def get_app_by_slug(slug: str) -> dict[str, Any] | None:
    """Fetch a single app by its human-stable slug.

    Used by deep-link install URLs (``/marketplace/visit-and-extract``)
    so the catalog can survive UUID-shuffling between environments.
    """
    if not slug:
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM marketplace_apps WHERE slug = %s", (slug,)
            )
            return _row_to_dict(cur.fetchone())


# ---------------------------------------------------------------------------
# tenant_app_installs — read + mutate paths
# ---------------------------------------------------------------------------


def list_installs(
    tenant_id: str, workspace_id: str | None = None
) -> list[dict[str, Any]]:
    """List a tenant's installs, optionally narrowed to one workspace.

    JOIN with ``marketplace_apps`` returns the app metadata inline so the
    "My Apps" UI doesn't have to N+1 fetch each app row. Newest first
    so the dashboard shows recent installs at the top.
    """
    if not _safe_uuid(tenant_id):
        return []
    where_sql = "WHERE i.tenant_id = %s"
    params: list[Any] = [tenant_id]
    if workspace_id is not None:
        if not _safe_uuid(workspace_id):
            return []
        where_sql += " AND i.workspace_id = %s"
        params.append(workspace_id)

    sql = (
        "SELECT i.id, i.tenant_id, i.workspace_id, i.app_id, "
        "       i.automation_id, i.installed_at, i.installed_by_user_id, "
        "       i.app_version, "
        "       a.slug AS app_slug, a.name AS app_name, "
        "       a.description AS app_description, a.icon_url AS app_icon_url, "
        "       a.category AS app_category, a.kind AS app_kind, "
        "       a.creator_name AS app_creator_name, "
        "       a.is_official AS app_is_official "
        "FROM tenant_app_installs i "
        "JOIN marketplace_apps a ON a.id = i.app_id "
        f"{where_sql} "
        "ORDER BY i.installed_at DESC"
    )
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


def install_app(
    workspace_id: str,
    app_id: str,
    user_id: str,
    automation_id: str,
) -> dict[str, Any] | None:
    """Record an install of ``app_id`` into ``workspace_id`` and bump count.

    Looks up the workspace's ``tenant_id`` and the app's ``version`` from
    the DB so callers don't have to plumb them through. Uses
    ``ON CONFLICT (workspace_id, app_id) DO NOTHING`` so a duplicate
    install attempt is a no-op (returns the existing row) rather than a
    crash — the marketplace UI can be optimistic without checking first.

    Bumps ``marketplace_apps.install_count`` only when a *new* row was
    inserted; idempotent re-installs don't inflate the popularity counter.

    Returns the install row (existing or newly created), or ``None`` if
    the workspace / app couldn't be resolved.
    """
    if not _safe_uuid(workspace_id) or not _safe_uuid(app_id):
        return None

    install_id = str(uuid.uuid4())

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Resolve tenant_id from workspace + app_version from the app.
            cur.execute(
                "SELECT tenant_id FROM workspaces WHERE id = %s",
                (workspace_id,),
            )
            ws = cur.fetchone()
            if ws is None:
                return None
            tenant_id = str(ws["tenant_id"])

            cur.execute(
                "SELECT version FROM marketplace_apps WHERE id = %s",
                (app_id,),
            )
            app_row = cur.fetchone()
            if app_row is None:
                return None
            app_version = app_row["version"]

            # Idempotent insert. RETURNING fires only on actual insert,
            # so a None result means a row already existed → fetch it.
            cur.execute(
                """INSERT INTO tenant_app_installs (
                       id, tenant_id, workspace_id, app_id,
                       automation_id, installed_by_user_id, app_version
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (workspace_id, app_id) DO NOTHING
                   RETURNING *""",
                (
                    install_id,
                    tenant_id,
                    workspace_id,
                    app_id,
                    automation_id,
                    user_id,
                    app_version,
                ),
            )
            row = cur.fetchone()
            if row is None:
                # Pre-existing install — fetch the row to return it.
                cur.execute(
                    """SELECT * FROM tenant_app_installs
                       WHERE workspace_id = %s AND app_id = %s""",
                    (workspace_id, app_id),
                )
                row = cur.fetchone()
            else:
                # Only bump the counter on a real insert.
                cur.execute(
                    """UPDATE marketplace_apps
                       SET install_count = install_count + 1,
                           updated_at = now()
                       WHERE id = %s""",
                    (app_id,),
                )
        conn.commit()
    return _row_to_dict(row)


def uninstall_app(workspace_id: str, app_id: str) -> bool:
    """Remove an install row and decrement ``install_count``.

    Returns ``True`` if a row was actually deleted; ``False`` if the
    install didn't exist (route layer maps to 404). The counter is
    decremented only when a row was deleted, and clamped to ``>= 0`` via
    ``GREATEST`` to defend against any drift from manual DB edits.
    """
    if not _safe_uuid(workspace_id) or not _safe_uuid(app_id):
        return False
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """DELETE FROM tenant_app_installs
                   WHERE workspace_id = %s AND app_id = %s""",
                (workspace_id, app_id),
            )
            removed = cur.rowcount > 0
            if removed:
                cur.execute(
                    """UPDATE marketplace_apps
                       SET install_count = GREATEST(install_count - 1, 0),
                           updated_at = now()
                       WHERE id = %s""",
                    (app_id,),
                )
        conn.commit()
    return removed


__all__ = [
    "list_public_apps",
    "get_app",
    "get_app_by_slug",
    "list_installs",
    "install_app",
    "uninstall_app",
]
