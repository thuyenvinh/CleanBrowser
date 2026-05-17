"""Overage billing helper.

When a tenant exceeds the per-period soft cap on a metered resource
(``automation_minutes_used`` today), instead of 402-blocking we record
an overage event + relay it to Stripe as a usage record if the plan has
metered billing configured. Unreported events accumulate locally so
that a missing/down Stripe doesn't lose revenue — a daily reconcile
job (Phase 7 phase 2) can replay them.

Public surface:

* :func:`emit_overage` — record one event (called from
  :func:`backend.quota.record_usage` after an over-cap increment).
* :func:`is_stripe_metered_available` — true iff ``STRIPE_SECRET_KEY``
  is configured. Exposed so callers / tests can branch.
* :func:`report_to_stripe` — best-effort wrapper around
  ``stripe.SubscriptionItem.create_usage_record``. Phase 7 phase 1
  doesn't yet wire this up from :func:`emit_overage` (we don't store
  the subscription-item id locally); it's kept here so the phase 2
  reconciler can use it without re-implementing the call.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def is_stripe_metered_available() -> bool:
    """True iff Stripe is configured. Used to short-circuit ``report_to_stripe``."""
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def report_to_stripe(subscription_item_id: str, units: int) -> str | None:
    """Report metered usage to Stripe.

    Returns the resulting Stripe ``usage_record`` id, or ``None`` on any
    failure (missing key, network error, API rejection). Failures are
    logged but never raised — the local overage event has already
    persisted, so a Stripe outage just means the reconcile job will
    pick the event up later.
    """
    if not is_stripe_metered_available():
        return None
    try:
        import stripe  # type: ignore[import-not-found]

        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        rec = stripe.SubscriptionItem.create_usage_record(
            subscription_item_id,
            quantity=units,
            timestamp="now",
            action="increment",
        )
        return rec.id
    except Exception:
        logger.exception(
            "overage: stripe usage record failed sub_item=%s",
            subscription_item_id,
        )
        return None


def emit_overage(
    tenant_id: str,
    resource: str,
    units: int,
    plan: dict[str, Any] | None = None,
    subscription: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Record one local overage event + best-effort Stripe usage report.

    Returns the persisted event dict, or ``None`` if the plan disallows
    overage / ``units`` is non-positive / the plan is missing.

    Phase 7 phase 1 deliberately skips the Stripe relay: we don't yet
    persist the metered subscription-item id alongside the
    subscription row, so we have nothing to call
    :func:`report_to_stripe` with. The local ledger is the source of
    truth — phase 2 will add the item-id and the daily reconcile.
    """
    if not plan or not plan.get("allow_overage"):
        return None
    if units <= 0:
        return None

    # Snapshot the unit price *at event time* so re-pricing the plan
    # later doesn't drift historical bills.
    unit_price = (
        plan.get("overage_price_per_minute_cents")
        if resource == "automation_minutes"
        else None
    )

    # Phase 7 phase 1: skip Stripe relay; persist locally only.
    stripe_id: str | None = None

    from .. import db_billing  # local import to avoid circular at module load

    return db_billing.record_overage_event(
        tenant_id=tenant_id,
        subscription_id=subscription["id"] if subscription else None,
        resource=resource,
        units=units,
        unit_price_cents=unit_price,
        stripe_usage_record_id=stripe_id,
    )


__all__ = [
    "emit_overage",
    "is_stripe_metered_available",
    "report_to_stripe",
]
