"""Overage billing helper.

When a tenant exceeds the per-period soft cap on a metered resource
(``automation_minutes_used`` today), instead of 402-blocking we record
an overage event + relay it to Stripe as a usage record if the plan has
metered billing configured. Unreported events accumulate locally so
that a missing/down Stripe doesn't lose revenue — the periodic flusher
(:mod:`backend.overage_worker`) drains the queue every minute.

Public surface:

* :func:`emit_overage` — record one event (called from
  :func:`backend.quota.record_usage` after an over-cap increment).
* :func:`is_stripe_metered_available` — true iff ``STRIPE_SECRET_KEY``
  is configured. Exposed so callers / tests can branch.
* :func:`report_to_stripe` — best-effort POST to Stripe's
  ``SubscriptionItem.create_usage_record``. Returns the Stripe record
  id on success or ``None`` on any failure; the event stays
  ``reported = false`` and the next tick retries.
* :func:`list_unreported_events` / :func:`mark_reported` — the
  queue/ack pair the flusher uses.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import psycopg2.extras

logger = logging.getLogger(__name__)


def is_stripe_metered_available() -> bool:
    """True iff Stripe is configured. Used to short-circuit ``report_to_stripe``."""
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def emit_overage(
    tenant_id: str,
    resource: str,
    delta: int,
    plan: dict[str, Any] | None = None,
    subscription: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Record one local overage event.

    Returns the persisted event dict, or ``None`` if the tenant has no
    *active* subscription / the plan disallows overage / ``delta`` is
    non-positive / the plan is missing.

    Subscription gate (C3): only subscriptions in the ``active`` status
    are charged. Trialing / past_due / cancelled subs (and tenants with
    no subscription row at all) must never reach Stripe — billing them
    overage during a trial would be a contract violation, and dunning
    states deserve human intervention before piling more charges on.

    Stripe relay is intentionally *not* done synchronously here — the
    request path stays on the fast path and the periodic
    :mod:`backend.overage_worker` flusher picks the event up within
    ``OVERAGE_FLUSH_INTERVAL_SECONDS``. That keeps Stripe latency /
    outages out of the user-visible action.
    """
    if delta <= 0:
        return None

    from .. import db_billing  # local import to avoid circular at module load

    # C3 gate: re-fetch the subscription rather than trusting the caller's
    # snapshot — :func:`backend.quota.record_usage` passes the active
    # subscription it already loaded, but other callers (tests, future
    # workers) may not, and the authoritative status check belongs here.
    if subscription is None:
        subscription = db_billing.get_active_subscription(tenant_id)

    if not subscription:
        logger.debug("no active sub for tenant %s — skip overage", tenant_id)
        return None

    status = subscription.get("status")
    if status != "active":
        # Trialing / past_due / cancelled / incomplete: keep the action
        # free for the user but do NOT record a billable event. The
        # daily reconciler has nothing to drain because there's no row.
        logger.info(
            "skip overage for tenant %s — sub status=%s", tenant_id, status
        )
        return None

    # Plan may be omitted by callers that only have the subscription;
    # fall back to ``db_billing.get_plan`` so the overage gate is
    # self-contained.
    if plan is None:
        plan_id = subscription.get("plan_id")
        plan = db_billing.get_plan(plan_id) if plan_id else None

    if not plan or not plan.get("allow_overage"):
        return None

    # Snapshot the unit price *at event time* so re-pricing the plan
    # later doesn't drift historical bills.
    unit_price = (
        plan.get("overage_price_per_minute_cents")
        if resource == "automation_minutes"
        else None
    )

    return db_billing.record_overage_event(
        tenant_id=tenant_id,
        subscription_id=subscription.get("id"),
        resource=resource,
        units=delta,
        unit_price_cents=unit_price,
        stripe_usage_record_id=None,
    )


# ---------------------------------------------------------------------------
# Flusher queue helpers (consumed by :mod:`backend.overage_worker`)
# ---------------------------------------------------------------------------


def list_unreported_events(limit: int = 500) -> list[dict[str, Any]]:
    """Return up to ``limit`` overage events still pending relay to Stripe.

    Ordered by ``occurred_at`` ascending so the flusher drains the
    queue oldest-first — that keeps Stripe usage timestamps in the same
    order events actually happened, which is what their reporting UI
    expects. The partial index
    ``ix_overage_events_unreported (reported, occurred_at) WHERE reported = false``
    backs this scan.
    """
    from ..database import get_db

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM overage_events
                   WHERE reported = false
                   ORDER BY occurred_at
                   LIMIT %s""",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall() or []]


def mark_reported(
    event_id: str, stripe_usage_record_id: str | None = None
) -> None:
    """Flip an overage event to ``reported = true`` and stamp the time.

    Optional ``stripe_usage_record_id`` is recorded for traceability —
    operators can grep the events table to find the corresponding
    Stripe object. We don't enforce non-null here because the same
    helper is reused by hypothetical out-of-band reconcilers that don't
    have a record id (e.g. when Stripe accepted the call but we lost
    the response).
    """
    from ..database import get_db

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE overage_events
                   SET reported = true,
                       reported_at = now(),
                       stripe_usage_record_id = COALESCE(%s, stripe_usage_record_id)
                   WHERE id = %s""",
                (stripe_usage_record_id, event_id),
            )
        conn.commit()


def report_to_stripe(event: dict[str, Any]) -> str | None:
    """POST one overage event to Stripe as a metered Usage Record.

    Returns the Stripe ``usage_record`` id on success, or ``None`` on
    any failure (Stripe not configured, missing line-item id, missing
    subscription id, network error, API rejection). Failures are
    logged but never raised — the event stays ``reported = false`` and
    the next flush tick retries it.

    Idempotency: passes ``event['id']`` as the ``idempotency_key``. If a
    previous attempt actually succeeded but we crashed before
    persisting the response, Stripe will return the same record on
    retry instead of double-billing.
    """
    from . import stripe_adapter

    if not stripe_adapter.is_configured():
        return None

    sub_id = event.get("subscription_id")
    if not sub_id:
        # Pre-subscription overage (shouldn't happen but defensive — an
        # event with no subscription can't be priced against any Stripe
        # item, so let it stay in the local ledger for manual review).
        logger.warning(
            "overage event %s has no subscription_id; skipping Stripe relay",
            event.get("id"),
        )
        return None

    from .. import db_billing

    item_id = db_billing.get_subscription_overage_item(sub_id)
    if not item_id:
        # Subscription exists but the webhook handler hasn't pinned the
        # line-item id yet (or the plan has no metered price). Skip
        # rather than error — once the item id is set we'll catch up.
        logger.warning(
            "subscription %s has no overage_subscription_item_id; "
            "skipping Stripe relay for event %s",
            sub_id,
            event.get("id"),
        )
        return None

    try:
        import stripe  # type: ignore[import-not-found]

        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

        # ``occurred_at`` is a TIMESTAMPTZ from Postgres; psycopg2 returns
        # it as a tz-aware datetime. Stripe wants a unix int. Fall back
        # to "now" if anything looks off rather than failing the post.
        occurred_at = event.get("occurred_at")
        timestamp_arg: int | str
        if hasattr(occurred_at, "timestamp"):
            try:
                timestamp_arg = int(occurred_at.timestamp())
            except (TypeError, ValueError):
                timestamp_arg = "now"
        else:
            timestamp_arg = "now"

        rec = stripe.SubscriptionItem.create_usage_record(
            item_id,
            quantity=int(event["units"]),
            timestamp=timestamp_arg,
            action="increment",
            idempotency_key=str(event["id"]),
        )
        return rec.id
    except Exception:
        logger.exception(
            "overage: stripe usage record failed event=%s sub_item=%s",
            event.get("id"),
            item_id,
        )
        return None


__all__ = [
    "emit_overage",
    "is_stripe_metered_available",
    "list_unreported_events",
    "mark_reported",
    "report_to_stripe",
]
