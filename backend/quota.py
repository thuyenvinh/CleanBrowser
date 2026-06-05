"""Quota enforcement: check against plan limits, record usage.

Wave 5 phase 1: pure module + dependency factory; route wiring deferred to
a later wave to avoid conflicting with the route refactors landing in
parallel (FFF/NN/OO touched routers, JJJ owns the quota module only).

The module purposefully takes a **lazy import** on :mod:`backend.db_billing`
(HHH is building it in the same wave). At collection time we don't want to
fail with ``ImportError`` if db_billing isn't yet on disk — the import only
fires when a caller actually invokes :func:`check_quota` /
:func:`record_usage`.

Public surface:

* :func:`check_quota` — pure inspection, returns a
  :class:`QuotaCheckResult` whose ``allowed`` field reflects whether the
  tenant can perform ``action`` once more.
* :func:`record_usage` — increment / snapshot the relevant usage counter
  after a successful action.
* :class:`QuotaCheckResult` — dataclass with a convenience
  :meth:`QuotaCheckResult.raise_if_exceeded` that maps to HTTP 402.

The matching dependency factory ``require_quota(action)`` lives in
:mod:`backend.dependencies` so router authors can wire it in via
``Depends(require_quota("create_profile"))`` once the wave-13 wiring task
arrives.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Actions a tenant might attempt that consume a plan-limited resource.
# Kept as a ``Literal`` so callers (and ``require_quota``) get a static
# typo check at the import site; the runtime dispatch happens via the
# ``_ACTION_MAP`` table below.
QuotaAction = Literal[
    "create_profile",
    "launch_profile",
    "invite_member",
    "run_automation",
    "create_workspace",
]

# Map ``action`` → ``(limit_field, usage_field, friendly_name)``.
#
# * ``limit_field`` is the key returned by ``db_billing.get_tenant_limits``;
#   ``None`` means the plan has no field for this action yet (treated as
#   unlimited — see ``create_workspace``).
# * ``usage_field`` is the key returned by ``db_billing.get_tenant_usage``
#   used to read the current consumption.
# * ``friendly_name`` is what shows up in the user-facing 402 reason.
_ACTION_MAP: dict[str, tuple[str | None, str | None, str]] = {
    "create_profile":   ("max_profiles",            "profile_count",           "profiles"),
    "launch_profile":   ("max_concurrent_runs",     "concurrent_runs_peak",    "concurrent runs"),
    "invite_member":    ("max_workspace_members",   "workspace_members_count", "team members"),
    "run_automation":   ("max_automation_minutes",  "automation_minutes_used", "automation minutes"),
    "create_workspace": (None,                      None,                      "workspaces"),
}


@dataclass
class QuotaCheckResult:
    """Outcome of a :func:`check_quota` call.

    ``allowed`` is the only field callers must inspect; the rest are
    populated for diagnostics and for the 402 payload built by
    :meth:`raise_if_exceeded`. ``limit`` is ``None`` when the plan grants
    the tenant unlimited use of the resource — in that case ``current``
    is reported as ``0`` because we deliberately skipped the usage read
    (saves a DB round-trip on the unlimited path).
    """

    allowed: bool
    limit: int | None
    current: int
    reason: str = ""
    # Phase 7 phase 1: ``True`` when ``allowed`` is granted *because*
    # the tenant's plan tolerates overage, not because they're under
    # the cap. Callers can surface this to the UI (e.g. an "extra
    # charges apply" badge) and to logging without re-querying the
    # plan row. Plain bool default keeps existing call sites
    # backwards-compatible.
    is_overage: bool = False

    def raise_if_exceeded(self) -> None:
        """Raise HTTP 402 Payment Required if this result is a denial.

        The 402 status is reused from the original HTTP spec ("reserved
        for future use") — it's the closest standard signal for "your
        plan needs an upgrade", and it's distinct from 403 (auth) so
        the frontend can route the error to an upgrade-prompt modal
        instead of the generic "permission denied" toast.
        """
        if not self.allowed:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "quota_exceeded",
                    "message": self.reason,
                    "limit": self.limit,
                    "current": self.current,
                },
            )


def check_quota(
    tenant_id: str,
    action: QuotaAction,
    requested_delta: int = 1,
) -> QuotaCheckResult:
    """Inspect whether ``tenant_id`` may perform ``action`` once more.

    Does **not** consume the quota — callers should follow a successful
    operation with :func:`record_usage` to bump the counter. This
    separation lets the dependency factory short-circuit the request
    early (before any DB writes) while the actual increment can be
    deferred to after the business logic has completed.

    ``requested_delta`` lets bulk operations check that a batch of size
    N would fit; defaults to 1 for single-item operations.

    Raises :class:`ValueError` on an unknown ``action`` so wiring bugs
    surface at the call site rather than silently passing the check.
    """
    if action not in _ACTION_MAP:
        raise ValueError(f"Unknown quota action: {action}")

    limit_field, usage_field, friendly = _ACTION_MAP[action]

    # No plan field for this action yet (e.g. ``create_workspace``) —
    # always allow. When we add a per-plan workspace cap we'll just fill
    # in the table entry and the rest of the flow already handles it.
    if limit_field is None:
        return QuotaCheckResult(allowed=True, limit=None, current=0)

    # Lazy import — :mod:`backend.db_billing` is owned by HHH and may not
    # yet be on disk when this module is first imported (collection
    # time). Deferring the import keeps `from backend import quota`
    # cheap and import-safe.
    from backend import db_billing

    limits = db_billing.get_tenant_limits(tenant_id)
    limit = limits.get(limit_field)
    if limit is None:
        # ``None`` in the limits dict explicitly means "unlimited" per the
        # db_billing contract — skip the usage read.
        return QuotaCheckResult(allowed=True, limit=None, current=0)

    usage = db_billing.get_tenant_usage(tenant_id)
    # ``or 0`` guards against the field being missing or stored as NULL
    # in the usage_counters row (e.g. a freshly created tenant before
    # any action has been recorded).
    current = usage.get(usage_field, 0) or 0

    if current + requested_delta > limit:
        # Phase 7 phase 1: ``run_automation`` is the first metered
        # resource that supports overage. If the tenant's plan has
        # ``allow_overage = true`` we let the action through and let
        # :func:`record_usage` emit an overage event after the fact.
        # Every other action still hard-caps with 402 — opening more
        # resources to overage is a phase-2 task.
        if action == "run_automation" and limits.get("allow_overage"):
            return QuotaCheckResult(
                allowed=True,
                limit=limit,
                current=current,
                is_overage=True,
                reason=(
                    f"Overage billing engaged for {friendly}: "
                    f"{current}/{limit}"
                ),
            )
        return QuotaCheckResult(
            allowed=False,
            limit=limit,
            current=current,
            reason=f"Plan limit reached for {friendly}: {current}/{limit}",
        )
    return QuotaCheckResult(allowed=True, limit=limit, current=current)


def record_usage(
    tenant_id: str,
    action: QuotaAction,
    delta: int = 1,
) -> None:
    """Update the usage counter for ``tenant_id`` after a successful action.

    Three update strategies are used depending on the action:

    * **snapshot** (``create_profile``, ``invite_member``): the counter
      is recomputed from the source-of-truth table. This is robust
      against missed increments / decrements (e.g. profile deletion)
      but costs a ``COUNT(*)``. Acceptable today because these actions
      are rare; a later wave will hand it off to a periodic reconciler.
    * **peak** (``launch_profile``): we track the *peak* concurrency
      seen in the current period, so we count currently-running
      sessions and ask ``db_billing.update_peak`` to clamp the stored
      value upwards.
    * **accumulate** (``run_automation``): a plain monotonic counter,
      delegated straight to ``db_billing.increment_counter``.

    All DB / billing errors are swallowed and logged — usage recording
    must never break the user-visible operation that just succeeded.
    """
    if action not in _ACTION_MAP:
        return
    _, usage_field, _ = _ACTION_MAP[action]
    if not usage_field:
        return

    try:
        from backend import db_billing  # lazy, same rationale as check_quota
        if action in ("create_profile", "invite_member"):
            db_billing.set_counter(
                tenant_id,
                usage_field,
                _recompute_snapshot(tenant_id, usage_field),
            )
        elif action == "launch_profile":
            db_billing.update_peak(
                tenant_id,
                usage_field,
                _count_running(tenant_id),
            )
        elif action == "run_automation":
            db_billing.increment_counter(tenant_id, usage_field, delta)
            # Phase 7 phase 1: if the bump pushed us over the cap and
            # the plan allows overage, emit a billable event. We pass
            # ``delta`` (not the cumulative over-cap total) so each
            # ``record_usage`` call charges only the minutes it just
            # added — the daily reconciler (phase 2) is in charge of
            # de-duplicating against Stripe. Wrapped in its own try so
            # an overage helper failure can't break the increment we
            # already committed above.
            try:
                limits = db_billing.get_tenant_limits(tenant_id)
                limit = limits.get("max_automation_minutes")
                if limit is not None and limits.get("allow_overage"):
                    usage = db_billing.get_tenant_usage(tenant_id)
                    used = usage.get(usage_field, 0) or 0
                    if used > limit:
                        from backend.billing import overage

                        sub = db_billing.get_active_subscription(tenant_id)
                        overage.emit_overage(
                            tenant_id,
                            "automation_minutes",
                            delta,
                            plan=limits,
                            subscription=sub,
                        )
            except Exception:
                logger.exception(
                    "record_usage: overage emission failed tenant=%s",
                    tenant_id,
                )
    except Exception:
        # Never propagate — the caller already committed the user action.
        logger.exception(
            "record_usage failed for action=%s tenant=%s", action, tenant_id
        )


def _recompute_snapshot(tenant_id: str, field: str) -> int:
    """Compute the true value of a snapshot field from source tables.

    Runs under :func:`backend.middleware_rls.system_context` so the
    restrictive RLS policies don't block the cross-tenant view (we're
    counting *this* tenant's rows but the connection's GUC is whatever
    the surrounding request had — which may not match if the caller is
    a worker / scheduler with no user context).
    """
    from backend.database import get_db
    from backend.middleware_rls import system_context

    with system_context():
        with get_db() as conn:
            with conn.cursor() as cur:
                if field == "profile_count":
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM profiles p
                        JOIN workspaces w ON w.id = p.workspace_id
                        WHERE w.tenant_id = %s
                        """,
                        (tenant_id,),
                    )
                elif field == "workspace_members_count":
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM workspace_members wm
                        JOIN workspaces w ON w.id = wm.workspace_id
                        WHERE w.tenant_id = %s
                        """,
                        (tenant_id,),
                    )
                else:
                    return 0
                row = cur.fetchone()
                return int(row[0]) if row else 0


def _count_running(tenant_id: str) -> int:
    """Count currently-running browser sessions across ``tenant_id``.

    ``ended_at IS NULL`` is the standard "session is live" predicate
    used throughout :mod:`backend.browser_manager`; mirroring it here
    keeps the peak metric consistent with the launch / stop bookkeeping
    those modules already maintain.
    """
    from backend.database import get_db
    from backend.middleware_rls import system_context

    with system_context():
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) FROM profile_sessions ps
                    JOIN profiles p ON p.id = ps.profile_id
                    JOIN workspaces w ON w.id = p.workspace_id
                    WHERE w.tenant_id = %s AND ps.ended_at IS NULL
                    """,
                    (tenant_id,),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
