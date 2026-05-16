"""Billing data layer: plans, subscriptions, usage counters.

Phase 5 wave 1 (task HHH). Mirrors the style of :mod:`backend.db_auth` and
:mod:`backend.db_proxy` — synchronous psycopg2 on the shared
:func:`backend.database.get_db` pool, returning plain ``dict`` rows from
``RealDictCursor`` so the route layer can serialise straight to JSON.

This module is intentionally *not* wired into Stripe / VNPay webhooks or
quota enforcement here — those land in subsequent Phase 5 waves (agent
III for payment-provider integration, agent JJJ for the
``backend.quota`` enforcement helpers that will call
:func:`get_tenant_limits` / :func:`get_tenant_usage`).

See ``docs/ARCHITECTURE`` §2.8 (billing & metering) and migration
``0015_add_billing`` for the schema this module wraps.
"""

from __future__ import annotations

import calendar
import datetime
import decimal
import uuid
from typing import Any

import psycopg2.extras

from .database import get_db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SUBSCRIPTION_STATUSES: frozenset[str] = frozenset(
    {"active", "trialing", "past_due", "cancelled", "expired"}
)

# A subscription in any of these statuses counts as "currently entitled" —
# matches the partial UNIQUE index ``ux_subscriptions_active`` defined in
# migration 0015. Keep the two definitions in sync.
ACTIVE_SUBSCRIPTION_STATUSES: frozenset[str] = frozenset(
    {"active", "trialing", "past_due"}
)

VALID_PAYMENT_PROVIDERS: frozenset[str] = frozenset(
    {"stripe", "vnpay", "manual"}
)

# Columns the app layer is allowed to PATCH via ``update_subscription``.
# Status is gated separately (validated against VALID_SUBSCRIPTION_STATUSES).
_UPDATABLE_SUBSCRIPTION_COLUMNS: frozenset[str] = frozenset(
    {
        "plan_id",
        "payment_provider",
        "provider_subscription_id",
        "provider_customer_id",
        "current_period_start",
        "current_period_end",
        "cancel_at_period_end",
        "trial_end",
    }
)

# Counter fields that accumulate over a period (monotonic). Anything else
# (e.g. ``profile_count``) is a snapshot — use ``set_counter`` instead.
_ACCUMULATING_COUNTER_FIELDS: frozenset[str] = frozenset(
    {"automation_minutes_used"}
)

# Counter fields written as a "current value" snapshot. ``storage_gb_used``
# accepts float (it lands in a NUMERIC(10,3) column); the others are int.
_SNAPSHOT_COUNTER_FIELDS: frozenset[str] = frozenset(
    {"profile_count", "workspace_members_count", "storage_gb_used"}
)

# Counter fields that track an all-time-period peak — written via GREATEST.
_PEAK_COUNTER_FIELDS: frozenset[str] = frozenset({"concurrent_runs_peak"})

# Plan fallback for tenants without an active subscription. The ``free``
# row is guaranteed to exist by the seed in migration 0015.
_DEFAULT_PLAN_ID = "free"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_uuid(value: Any) -> bool:
    """True iff ``value`` parses as a UUID. Defensive guard for ID params."""
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    """Normalise a psycopg2 RealDict row for JSON serialisation.

    Stringifies UUIDs / datetimes / dates (parity with :mod:`db_auth` and
    :mod:`db_proxy`) and converts ``Decimal`` to ``float`` so the
    ``storage_gb_used`` NUMERIC column lands as a plain JSON number rather
    than a string. Precision past the column's ``(10,3)`` scale is
    irrelevant for the dashboards that consume it.
    """
    if row is None:
        return None
    out = dict(row)
    for key, val in list(out.items()):
        if isinstance(val, uuid.UUID):
            out[key] = str(val)
        elif isinstance(val, datetime.datetime):
            out[key] = val.isoformat()
        elif isinstance(val, datetime.date):
            out[key] = val.isoformat()
        elif isinstance(val, decimal.Decimal):
            out[key] = float(val)
    return out


def _require_status(status: str) -> None:
    if status not in VALID_SUBSCRIPTION_STATUSES:
        raise ValueError(
            f"invalid subscription status {status!r}; must be one of "
            f"{sorted(VALID_SUBSCRIPTION_STATUSES)}"
        )


def _require_payment_provider(provider: str | None) -> None:
    if provider is None:
        return
    if provider not in VALID_PAYMENT_PROVIDERS:
        raise ValueError(
            f"invalid payment_provider {provider!r}; must be one of "
            f"{sorted(VALID_PAYMENT_PROVIDERS)}"
        )


def _current_period_bounds(
    today: datetime.date | None = None,
) -> tuple[datetime.date, datetime.date]:
    """Return (period_start, period_end) for the current calendar month UTC.

    ``period_start`` is the first of the month; ``period_end`` is the last
    day (e.g. 2026-05-01 / 2026-05-31). Using ``date`` rather than
    timestamps keeps the UNIQUE (tenant_id, period_start) key trivially
    deterministic and avoids any TZ-arithmetic ambiguity at the boundary.
    """
    if today is None:
        today = datetime.datetime.now(datetime.timezone.utc).date()
    start = today.replace(day=1)
    last_day = calendar.monthrange(today.year, today.month)[1]
    end = today.replace(day=last_day)
    return start, end


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


def list_plans(public_only: bool = True) -> list[dict[str, Any]]:
    """Return the plan catalogue ordered by ``sort_order``.

    With ``public_only=True`` (default), private plans (e.g. legacy /
    enterprise custom tiers with ``is_public=false``) are filtered out so
    the pricing page only shows what is meant to be sold.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if public_only:
                cur.execute(
                    """SELECT * FROM plans
                       WHERE is_public = true
                       ORDER BY sort_order ASC, id ASC"""
                )
            else:
                cur.execute(
                    """SELECT * FROM plans
                       ORDER BY sort_order ASC, id ASC"""
                )
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


def get_plan(plan_id: str) -> dict[str, Any] | None:
    """Fetch one plan by slug (``'free'``, ``'pro'``, ...)."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM plans WHERE id = %s", (plan_id,))
            return _row_to_dict(cur.fetchone())


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------


def get_active_subscription(tenant_id: str) -> dict[str, Any] | None:
    """Return the tenant's currently entitling subscription, if any.

    Matches the partial UNIQUE index from migration 0015 — at most one row
    can satisfy this filter, so ``LIMIT 1`` is purely defensive. ``None``
    means the tenant should fall back to the default plan.
    """
    if not _is_uuid(tenant_id):
        return None
    statuses = tuple(sorted(ACTIVE_SUBSCRIPTION_STATUSES))
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM subscriptions
                   WHERE tenant_id = %s AND status = ANY(%s)
                   ORDER BY created_at DESC
                   LIMIT 1""",
                (tenant_id, list(statuses)),
            )
            return _row_to_dict(cur.fetchone())


def get_subscription_by_provider_id(
    provider_subscription_id: str,
) -> dict[str, Any] | None:
    """Look up a subscription by external provider ID (Stripe / VNPay).

    Used by webhook handlers to map an incoming event back to our row.
    """
    if not provider_subscription_id:
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM subscriptions
                   WHERE provider_subscription_id = %s
                   ORDER BY created_at DESC
                   LIMIT 1""",
                (provider_subscription_id,),
            )
            return _row_to_dict(cur.fetchone())


def create_subscription(
    tenant_id: str,
    plan_id: str,
    status: str = "active",
    payment_provider: str | None = None,
    provider_subscription_id: str | None = None,
    provider_customer_id: str | None = None,
    current_period_start: datetime.datetime | None = None,
    current_period_end: datetime.datetime | None = None,
    trial_end: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Insert a subscription row, returning the persisted record.

    Validates ``status`` and ``payment_provider`` against their allow
    lists. Will raise ``psycopg2.errors.UniqueViolation`` (bubbling out)
    if the tenant already has an active-ish subscription and ``status``
    falls into the active set — that constraint is what the partial
    UNIQUE index ``ux_subscriptions_active`` enforces. Callers that want
    to swap plans should ``cancel_subscription(immediate=True)`` first or
    use :func:`update_subscription`.
    """
    _require_status(status)
    _require_payment_provider(payment_provider)
    subscription_id = str(uuid.uuid4())
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO subscriptions (
                    id, tenant_id, plan_id, status,
                    payment_provider, provider_subscription_id,
                    provider_customer_id,
                    current_period_start, current_period_end, trial_end
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s,
                    %s,
                    %s, %s, %s
                ) RETURNING *""",
                (
                    subscription_id,
                    tenant_id,
                    plan_id,
                    status,
                    payment_provider,
                    provider_subscription_id,
                    provider_customer_id,
                    current_period_start,
                    current_period_end,
                    trial_end,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


def update_subscription(
    subscription_id: str, **fields: Any
) -> dict[str, Any] | None:
    """Patch a subscription row. Unknown columns are silently ignored.

    ``status`` is special-cased: it is validated against
    ``VALID_SUBSCRIPTION_STATUSES`` before being applied. ``updated_at``
    is bumped to ``now()`` on every successful UPDATE so consumers can
    detect drift since their last poll. Returns ``None`` if the row id
    didn't match anything (e.g. a stale webhook).
    """
    if not _is_uuid(subscription_id):
        return None
    if not fields:
        return _get_subscription_by_id(subscription_id)

    update_cols: list[str] = []
    update_vals: list[Any] = []

    if "status" in fields:
        _require_status(fields["status"])
        update_cols.append("status = %s")
        update_vals.append(fields["status"])

    if "payment_provider" in fields:
        _require_payment_provider(fields["payment_provider"])

    for col in _UPDATABLE_SUBSCRIPTION_COLUMNS:
        if col in fields:
            update_cols.append(f"{col} = %s")
            update_vals.append(fields[col])

    if not update_cols:
        return _get_subscription_by_id(subscription_id)

    update_cols.append("updated_at = now()")
    update_vals.append(subscription_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"UPDATE subscriptions SET {', '.join(update_cols)} "
                f"WHERE id = %s RETURNING *",
                update_vals,
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)


def cancel_subscription(
    subscription_id: str, immediate: bool = False
) -> dict[str, Any] | None:
    """Cancel a subscription either immediately or at period end.

    ``immediate=True`` flips ``status`` to ``'cancelled'`` straight away
    — the tenant loses entitlement on the next quota check. The default
    ``immediate=False`` sets ``cancel_at_period_end=true`` and leaves the
    status alone; the subscription keeps serving the tenant until
    ``current_period_end``, at which point a separate cron / webhook
    flips the status (that flip is not handled here).
    """
    if not _is_uuid(subscription_id):
        return None
    if immediate:
        return update_subscription(
            subscription_id,
            status="cancelled",
            cancel_at_period_end=False,
        )
    return update_subscription(subscription_id, cancel_at_period_end=True)


def _get_subscription_by_id(
    subscription_id: str,
) -> dict[str, Any] | None:
    """Internal helper — fetch a subscription by PK without further checks."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM subscriptions WHERE id = %s",
                (subscription_id,),
            )
            return _row_to_dict(cur.fetchone())


# ---------------------------------------------------------------------------
# Usage counters
# ---------------------------------------------------------------------------


def get_or_create_current_period(tenant_id: str) -> dict[str, Any]:
    """Return the current-month usage row, inserting a zeroed one if missing.

    Period = current UTC calendar month. The UPSERT uses the
    ``uq_usage_counters_tenant_period`` constraint and a no-op ``DO
    UPDATE`` so we can always ``RETURNING *`` regardless of insert/match.
    Safe to call from concurrent requests — Postgres serialises the
    constraint check.
    """
    period_start, period_end = _current_period_bounds()
    counter_id = str(uuid.uuid4())
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO usage_counters (
                    id, tenant_id, period_start, period_end
                ) VALUES (%s, %s, %s, %s)
                ON CONFLICT ON CONSTRAINT uq_usage_counters_tenant_period
                DO UPDATE SET updated_at = usage_counters.updated_at
                RETURNING *""",
                (counter_id, tenant_id, period_start, period_end),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


def increment_counter(
    tenant_id: str, field: str, delta: int = 1
) -> dict[str, Any]:
    """Add ``delta`` to an accumulating counter field for the current period.

    Only fields in ``_ACCUMULATING_COUNTER_FIELDS`` (currently just
    ``automation_minutes_used``) are accepted; trying to increment a
    snapshot column like ``profile_count`` would race against the
    authoritative source so callers must use :func:`set_counter` instead.
    Ensures the row exists first via :func:`get_or_create_current_period`.
    """
    if field not in _ACCUMULATING_COUNTER_FIELDS:
        raise ValueError(
            f"field {field!r} is not an accumulating counter; "
            f"valid choices: {sorted(_ACCUMULATING_COUNTER_FIELDS)}"
        )
    get_or_create_current_period(tenant_id)
    period_start, _ = _current_period_bounds()
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""UPDATE usage_counters
                    SET {field} = {field} + %s,
                        updated_at = now()
                    WHERE tenant_id = %s AND period_start = %s
                    RETURNING *""",
                (delta, tenant_id, period_start),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


def set_counter(
    tenant_id: str, field: str, value: int | float
) -> dict[str, Any]:
    """Overwrite a snapshot counter (``profile_count`` et al.) with ``value``.

    Used by the metering background job that recomputes the
    authoritative totals from the source-of-truth tables (e.g.
    ``SELECT count(*) FROM profiles``) and pushes them into
    ``usage_counters`` for cheap dashboard reads.
    """
    if field not in _SNAPSHOT_COUNTER_FIELDS:
        raise ValueError(
            f"field {field!r} is not a snapshot counter; "
            f"valid choices: {sorted(_SNAPSHOT_COUNTER_FIELDS)}"
        )
    get_or_create_current_period(tenant_id)
    period_start, _ = _current_period_bounds()
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""UPDATE usage_counters
                    SET {field} = %s,
                        updated_at = now()
                    WHERE tenant_id = %s AND period_start = %s
                    RETURNING *""",
                (value, tenant_id, period_start),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


def update_peak(
    tenant_id: str, field: str, value: int
) -> dict[str, Any]:
    """Bump a peak counter with ``GREATEST(current, value)``.

    Only ``concurrent_runs_peak`` is currently a peak column; callers
    pass the just-observed concurrent-run count and we keep the largest
    value ever seen in the period. Never decreases.
    """
    if field not in _PEAK_COUNTER_FIELDS:
        raise ValueError(
            f"field {field!r} is not a peak counter; "
            f"valid choices: {sorted(_PEAK_COUNTER_FIELDS)}"
        )
    get_or_create_current_period(tenant_id)
    period_start, _ = _current_period_bounds()
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""UPDATE usage_counters
                    SET {field} = GREATEST({field}, %s),
                        updated_at = now()
                    WHERE tenant_id = %s AND period_start = %s
                    RETURNING *""",
                (value, tenant_id, period_start),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Enforcement helpers (consumed by ``backend.quota`` — agent JJJ)
# ---------------------------------------------------------------------------


def get_tenant_limits(tenant_id: str) -> dict[str, Any]:
    """Return the effective plan limits for ``tenant_id``.

    Looks up the tenant's active subscription and returns the joined
    plan row. When no active sub exists, falls back to the ``free``
    plan so the rest of the system can always assume *some* limits are
    in effect. ``None`` values on the limit columns mean "unlimited".

    Output shape matches a plan row plus ``plan_id`` for callers that
    don't want to re-read ``id``.
    """
    sub = get_active_subscription(tenant_id)
    plan_id = sub["plan_id"] if sub else _DEFAULT_PLAN_ID
    plan = get_plan(plan_id)
    if plan is None:
        # Defensive: someone dropped the ``free`` seed. Fail loud rather
        # than silently grant unlimited access.
        raise RuntimeError(
            f"plan {plan_id!r} not found and no fallback available — "
            "seed in migration 0015_add_billing may have been removed"
        )
    return plan


def get_tenant_usage(tenant_id: str) -> dict[str, Any]:
    """Return the current-period usage row joined with live source counts.

    Snapshot fields stored on ``usage_counters`` (``profile_count``,
    ``workspace_members_count``) are *also* computed live here from the
    source-of-truth tables so the answer is always fresh — the stored
    snapshot exists for cheap historical aggregation but should never
    be trusted for "can this tenant create one more profile?" gating.

    Live counts:
      * ``profile_count``           — ``profiles`` joined through
        ``workspaces`` for this tenant.
      * ``workspace_members_count`` — DISTINCT users across all
        workspaces of this tenant.

    All other fields come straight from ``usage_counters``. The current
    period row is auto-created if missing.
    """
    counter = get_or_create_current_period(tenant_id)

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT count(*) AS n
                   FROM profiles p
                   JOIN workspaces w ON w.id = p.workspace_id
                   WHERE w.tenant_id = %s""",
                (tenant_id,),
            )
            row = cur.fetchone()
            live_profiles = int(row["n"]) if row else 0

            cur.execute(
                """SELECT count(DISTINCT m.user_id) AS n
                   FROM workspace_members m
                   JOIN workspaces w ON w.id = m.workspace_id
                   WHERE w.tenant_id = %s""",
                (tenant_id,),
            )
            row = cur.fetchone()
            live_members = int(row["n"]) if row else 0

    counter["profile_count"] = live_profiles
    counter["workspace_members_count"] = live_members
    return counter


__all__ = [
    "ACTIVE_SUBSCRIPTION_STATUSES",
    "VALID_PAYMENT_PROVIDERS",
    "VALID_SUBSCRIPTION_STATUSES",
    "cancel_subscription",
    "create_subscription",
    "get_active_subscription",
    "get_or_create_current_period",
    "get_plan",
    "get_subscription_by_provider_id",
    "get_tenant_limits",
    "get_tenant_usage",
    "increment_counter",
    "list_plans",
    "set_counter",
    "update_peak",
    "update_subscription",
]
