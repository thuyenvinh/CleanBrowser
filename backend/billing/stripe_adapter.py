"""Stripe integration. Configure via env: STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET.

When STRIPE_SECRET_KEY missing → dev mode (all endpoints return 503)."""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return bool(os.environ.get("STRIPE_SECRET_KEY"))


def _client():
    import stripe

    stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
    return stripe


def create_or_get_customer(tenant_id: str, email: str, name: str | None = None) -> str:
    """Returns Stripe customer id. Idempotent via metadata.tenant_id search."""
    stripe = _client()
    # Search existing
    results = stripe.Customer.search(query=f'metadata["tenant_id"]:"{tenant_id}"')
    if results.data:
        return results.data[0].id
    c = stripe.Customer.create(email=email, name=name, metadata={"tenant_id": tenant_id})
    return c.id


def create_checkout_session(
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    tenant_id: str,
) -> dict:
    """Returns {url, session_id}."""
    stripe = _client()
    s = stripe.checkout.Session.create(
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"tenant_id": tenant_id},
        subscription_data={"metadata": {"tenant_id": tenant_id}},
    )
    return {"url": s.url, "session_id": s.id}


def create_portal_session(customer_id: str, return_url: str) -> str:
    stripe = _client()
    p = stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)
    return p.url


def verify_webhook(payload: bytes, signature: str) -> dict:
    """Returns event dict or raises."""
    stripe = _client()
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET not configured")
    return stripe.Webhook.construct_event(payload, signature, secret)


def handle_event(event: dict) -> dict[str, Any]:
    """Process subscription lifecycle events. Returns summary dict.

    Caller (router) persists to DB via db_billing."""
    et = event["type"]
    data = event["data"]["object"]
    summary: dict[str, Any] = {"event_type": et, "handled": False}

    if et in ("customer.subscription.created", "customer.subscription.updated"):
        tenant_id = (data.get("metadata") or {}).get("tenant_id")
        if not tenant_id:
            return summary
        summary.update(
            {
                "handled": True,
                "tenant_id": tenant_id,
                "subscription_id": data["id"],
                "customer_id": data["customer"],
                "plan_id": _resolve_plan_id_from_price(data),
                "status": data["status"],
                "current_period_start": data.get("current_period_start"),
                "current_period_end": data.get("current_period_end"),
                "cancel_at_period_end": data.get("cancel_at_period_end", False),
                "trial_end": data.get("trial_end"),
            }
        )
    elif et == "customer.subscription.deleted":
        tenant_id = (data.get("metadata") or {}).get("tenant_id")
        summary.update(
            {
                "handled": True,
                "tenant_id": tenant_id,
                "subscription_id": data["id"],
                "status": "cancelled",
            }
        )
    return summary


def _resolve_plan_id_from_price(subscription_obj: dict) -> str | None:
    """Find our internal plan_id matching the Stripe price."""
    # Lazy import to avoid circular
    from backend import db_billing

    items = subscription_obj.get("items", {}).get("data", [])
    if not items:
        return None
    stripe_price = items[0]["price"]["id"]
    for p in db_billing.list_plans(public_only=False):
        if p.get("stripe_price_id") == stripe_price:
            return p["id"]
    return None
