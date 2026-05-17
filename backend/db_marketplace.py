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

    Phase 6 phase 2: also gates on ``moderation_status = 'approved'`` so
    pending/rejected user submissions never leak into the public catalog.
    The 0019 migration reshapes ``ix_marketplace_apps_category`` to match
    this predicate, so the filter remains index-friendly.
    """
    where_sql = (
        "WHERE is_public = true AND moderation_status = 'approved'"
    )
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


# ---------------------------------------------------------------------------
# Creator portal — user submissions + admin moderation queue
# ---------------------------------------------------------------------------
#
# Phase 6 phase 2 surface. Submissions land in ``moderation_status='pending'``
# with ``is_public=false`` so they're invisible to the public listing until
# an admin approves. ``install_count`` starts at 0; ``is_official`` stays
# false (seed migration is the only path to the official badge). Slug
# uniqueness is enforced by the existing column-level UNIQUE constraint —
# the HTTP layer does a friendlier pre-check via :func:`get_app_by_slug`.


def submit_app(
    slug: str,
    name: str,
    description: str | None,
    kind: str,
    dsl_json: dict[str, Any] | None,
    script_language: str | None,
    script_code: str | None,
    creator_name: str | None,
    creator_url: str | None,
    submitted_by_user_id: str,
    category: str | None = None,
    long_description: str | None = None,
    icon_url: str | None = None,
) -> dict[str, Any]:
    """Insert a user-submitted app row in 'pending' status.

    Forces ``is_public=false`` and ``is_official=false`` regardless of
    caller intent — promotion to public happens via :func:`approve_app`
    only. Returns the freshly created row (including the generated UUID
    and the server-side ``submitted_at`` timestamp).
    """
    import json

    new_id = str(uuid.uuid4())
    # psycopg2 doesn't auto-adapt dicts to JSONB; round-trip via json.dumps
    # so the column receives a plain text payload it can cast.
    dsl_payload = json.dumps(dsl_json) if dsl_json is not None else None

    sql = (
        "INSERT INTO marketplace_apps ("
        "    id, slug, name, description, long_description, icon_url,"
        "    category, kind, dsl_json, script_language, script_code,"
        "    creator_name, creator_url, is_official, is_public,"
        "    moderation_status, submitted_by_user_id, submitted_at"
        ") VALUES ("
        "    %s, %s, %s, %s, %s, %s,"
        "    %s, %s, %s::jsonb, %s, %s,"
        "    %s, %s, false, false,"
        "    'pending', %s, now()"
        ") RETURNING *"
    )

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                sql,
                (
                    new_id,
                    slug,
                    name,
                    description,
                    long_description,
                    icon_url,
                    category,
                    kind,
                    dsl_payload,
                    script_language,
                    script_code,
                    creator_name,
                    creator_url,
                    submitted_by_user_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


def list_pending() -> list[dict[str, Any]]:
    """Return apps awaiting moderation, newest first.

    Hits the ``ix_marketplace_apps_moderation`` partial index added by
    migration 0019. Includes ``rejected`` rows so the admin queue can
    surface a "recently rejected" tab without an extra query.
    """
    sql = (
        "SELECT * FROM marketplace_apps "
        "WHERE moderation_status IN ('pending', 'rejected') "
        "ORDER BY submitted_at DESC NULLS LAST"
    )
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


def approve_app(
    app_id: str, moderation_notes: str | None = None
) -> dict[str, Any] | None:
    """Flip a submitted app to approved + public.

    Returns the updated row, or ``None`` if the id is bad / missing so
    callers can map to 404 cleanly. ``updated_at`` is bumped so the
    listing's secondary sort (name ASC) reflects the moderation action.
    """
    if not _safe_uuid(app_id):
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "UPDATE marketplace_apps "
                "SET moderation_status = 'approved', "
                "    is_public = true, "
                "    moderation_notes = %s, "
                "    updated_at = now() "
                "WHERE id = %s "
                "RETURNING *",
                (moderation_notes, app_id),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)


def reject_app(
    app_id: str, moderation_notes: str
) -> dict[str, Any] | None:
    """Mark a submission rejected; keeps it invisible to the public listing.

    Rejection notes are required at the HTTP layer (so the creator gets
    actionable feedback); we still accept the parameter unconditionally
    here to keep the data layer's contract simple.
    """
    if not _safe_uuid(app_id):
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "UPDATE marketplace_apps "
                "SET moderation_status = 'rejected', "
                "    is_public = false, "
                "    moderation_notes = %s, "
                "    updated_at = now() "
                "WHERE id = %s "
                "RETURNING *",
                (moderation_notes, app_id),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Creator dashboard — revenue share + earnings ledger (Phase 6 phase 3)
# ---------------------------------------------------------------------------
#
# Surface for migration 0025. Earnings are recorded by the install endpoint
# the moment a paid app is installed; the row is owned by the creator (via
# ``creator_user_id``) and carries the revenue split snapshotted at event
# time so re-pricing the app later cannot rewrite history.
#
# The 14-day pending → available window matches Stripe's chargeback window
# convention: the earning is held in escrow until the buyer can no longer
# request a refund, at which point a daily worker (``mark_earnings_available_due``)
# flips the status so the creator can request payout.

# Refund window before pending earnings become available for payout. Matches
# Stripe's default chargeback window so escrow expires aligned with the
# payment provider's own dispute timeline.
_AVAILABLE_AFTER_DAYS: int = 14


# Columns selected by the creator dashboard list — includes the app slug/name
# so the UI doesn't N+1 fetch each app row.
_EARNINGS_LIST_COLUMNS: str = (
    "e.id, e.app_id, e.install_id, e.creator_user_id, e.buyer_tenant_id, "
    "e.gross_cents, e.creator_cents, e.platform_cents, e.currency, "
    "e.status, e.available_at, e.paid_out_at, e.created_at, "
    "a.slug AS app_slug, a.name AS app_name"
)


def record_earning(
    app: dict[str, Any],
    install_id: str | None,
    buyer_tenant_id: str,
    gross_cents: int,
) -> dict[str, Any] | None:
    """Compute the revenue split + insert one ``marketplace_earnings`` row.

    No-ops (returns ``None``) when:

    * the app has no ``creator_user_id`` (seeded official apps fall here —
      the platform keeps 100% of revenue with no creator to credit), or
    * ``gross_cents <= 0`` (free apps must never spawn a ledger row).

    The split is snapshotted at event time: ``creator_cents = gross *
    revenue_share_pct // 100`` (integer division, platform absorbs the
    rounding remainder via ``platform_cents = gross - creator_cents``).
    Both columns are stored explicitly so a future ``UPDATE
    marketplace_apps SET revenue_share_pct = ...`` cannot retroactively
    change historical bills.

    ``available_at`` is set to ``now() + 14 days`` so the payout worker
    (``mark_earnings_available_due``) can promote the row without
    recomputing the threshold each pass.
    """
    creator_user_id = app.get("creator_user_id")
    if not creator_user_id or gross_cents <= 0:
        return None

    share_pct = int(app.get("revenue_share_pct") or 70)
    # Clamp to [0, 100] so a corrupted column value can't yield negative
    # creator_cents (which would also blow the NOT NULL check below via
    # the ``creator_cents >= 0`` invariant the dashboard relies on).
    share_pct = max(0, min(100, share_pct))
    creator_cents = (int(gross_cents) * share_pct) // 100
    platform_cents = int(gross_cents) - creator_cents

    new_id = str(uuid.uuid4())
    available_at = datetime.datetime.now(
        datetime.timezone.utc
    ) + datetime.timedelta(days=_AVAILABLE_AFTER_DAYS)

    sql = (
        "INSERT INTO marketplace_earnings ("
        "    id, app_id, install_id, creator_user_id, buyer_tenant_id,"
        "    gross_cents, creator_cents, platform_cents,"
        "    status, available_at"
        ") VALUES ("
        "    %s, %s, %s, %s, %s,"
        "    %s, %s, %s,"
        "    'pending', %s"
        ") RETURNING *"
    )
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                sql,
                (
                    new_id,
                    app.get("id"),
                    install_id,
                    creator_user_id,
                    buyer_tenant_id,
                    int(gross_cents),
                    creator_cents,
                    platform_cents,
                    available_at,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)


def list_earnings_for_creator(
    user_id: str,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return earnings rows where the caller is the creator, newest first.

    Hits ``ix_marketplace_earnings_creator`` for the ordering. The optional
    ``status`` filter narrows by lifecycle stage
    (``pending`` / ``available`` / ``paid_out`` / ``refunded``); ``None``
    returns all statuses so the dashboard can tab through them client-side.
    """
    if not _safe_uuid(user_id):
        return []
    where_sql = "WHERE e.creator_user_id = %s"
    params: list[Any] = [user_id]
    if status is not None:
        where_sql += " AND e.status = %s"
        params.append(status)
    params.append(int(limit))

    sql = (
        f"SELECT {_EARNINGS_LIST_COLUMNS} "
        "FROM marketplace_earnings e "
        "JOIN marketplace_apps a ON a.id = e.app_id "
        f"{where_sql} "
        "ORDER BY e.created_at DESC "
        "LIMIT %s"
    )
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


def creator_summary(user_id: str) -> dict[str, Any]:
    """Aggregate counters for the dashboard's summary cards.

    Returns ``{total_apps, total_installs, pending_cents, available_cents,
    paid_out_cents}``. Two queries (one over ``marketplace_apps`` for app
    + install counts, one over ``marketplace_earnings`` for the monetary
    rollup) — keeps each plan simple and indexable rather than fighting
    Postgres's planner with a single mega-JOIN.

    Returns zeroed values for unknown / malformed user ids so the UI can
    render the empty state without a special-case branch.
    """
    empty = {
        "total_apps": 0,
        "total_installs": 0,
        "pending_cents": 0,
        "available_cents": 0,
        "paid_out_cents": 0,
    }
    if not _safe_uuid(user_id):
        return empty

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # App + cumulative install counts. Hits the row directly via the
            # creator_user_id column (small set per creator, no index needed
            # at the volumes we expect this phase).
            cur.execute(
                "SELECT COUNT(*) AS apps, "
                "       COALESCE(SUM(install_count), 0) AS installs "
                "FROM marketplace_apps "
                "WHERE creator_user_id = %s",
                (user_id,),
            )
            app_row = cur.fetchone() or {}

            # Money rollup, bucketed by lifecycle status. FILTER avoids
            # multiple round-trips and lets Postgres scan the partial
            # creator index once.
            cur.execute(
                "SELECT "
                "  COALESCE(SUM(creator_cents) FILTER (WHERE status = 'pending'), 0) AS pending, "
                "  COALESCE(SUM(creator_cents) FILTER (WHERE status = 'available'), 0) AS available, "
                "  COALESCE(SUM(creator_cents) FILTER (WHERE status = 'paid_out'), 0) AS paid_out "
                "FROM marketplace_earnings "
                "WHERE creator_user_id = %s",
                (user_id,),
            )
            money_row = cur.fetchone() or {}

    return {
        "total_apps": int(app_row.get("apps") or 0),
        "total_installs": int(app_row.get("installs") or 0),
        "pending_cents": int(money_row.get("pending") or 0),
        "available_cents": int(money_row.get("available") or 0),
        "paid_out_cents": int(money_row.get("paid_out") or 0),
    }


def mark_earnings_available_due() -> int:
    """Worker helper: promote pending earnings whose escrow has expired.

    Flips ``status='pending' → 'available'`` for every row where
    ``available_at <= now()``. Returns the row count so the worker can
    log a tick summary. Idempotent — re-running the worker on the same
    minute is a no-op once the rows have been flipped.

    Designed to be called by a daily cron / scheduler (not the request
    path) so the dashboard's "available_cents" total reflects yesterday's
    promotions on the morning of day 15.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE marketplace_earnings "
                "SET status = 'available' "
                "WHERE status = 'pending' "
                "  AND available_at IS NOT NULL "
                "  AND available_at <= now()"
            )
            count = cur.rowcount
        conn.commit()
    return int(count or 0)


def list_apps_by_creator(user_id: str) -> list[dict[str, Any]]:
    """Return every app where the caller is the creator (any moderation status).

    Used by the creator dashboard's "My Apps" tab — must surface pending /
    rejected submissions too so the creator can track moderation outcomes
    without having to know the slug.
    """
    if not _safe_uuid(user_id):
        return []
    sql = (
        "SELECT id, slug, name, description, category, kind, version, "
        "       install_count, is_official, is_public, moderation_status, "
        "       moderation_notes, price_cents, revenue_share_pct, "
        "       created_at, updated_at, submitted_at "
        "FROM marketplace_apps "
        "WHERE creator_user_id = %s "
        "ORDER BY created_at DESC"
    )
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (user_id,))
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


__all__ = [
    "list_public_apps",
    "get_app",
    "get_app_by_slug",
    "list_installs",
    "install_app",
    "uninstall_app",
    "submit_app",
    "list_pending",
    "approve_app",
    "reject_app",
    "record_earning",
    "list_earnings_for_creator",
    "creator_summary",
    "mark_earnings_available_due",
    "list_apps_by_creator",
]
