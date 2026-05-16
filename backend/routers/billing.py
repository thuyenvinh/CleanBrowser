"""Billing endpoints — Stripe checkout, customer portal, webhook."""
from __future__ import annotations

import logging
from datetime import datetime, timezone as tz

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ..billing import stripe_adapter
from ..dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/billing", tags=["billing"])


@router.get("/plans")
async def list_plans(_: dict = Depends(get_current_user)):
    from .. import db_billing

    return db_billing.list_plans(public_only=True)


@router.get("/subscription")
async def get_subscription(user: dict = Depends(get_current_user)):
    """Return active subscription + plan + current usage."""
    from .. import db_billing

    sub = db_billing.get_active_subscription(user["tenant_id"])
    plan_id = sub["plan_id"] if sub else "free"
    plan = db_billing.get_plan(plan_id)
    usage = db_billing.get_or_create_current_period(user["tenant_id"])
    return {"subscription": sub, "plan": plan, "usage": usage}


@router.post("/checkout")
async def start_checkout(
    body: dict, request: Request, user: dict = Depends(get_current_user)
):
    """body: {plan_id, success_url?, cancel_url?}"""
    from .. import db_billing

    if not stripe_adapter.is_configured():
        raise HTTPException(503, "Stripe not configured")
    plan_id = body.get("plan_id")
    plan = db_billing.get_plan(plan_id) if plan_id else None
    if not plan:
        raise HTTPException(404, "Plan not found")
    if not plan.get("stripe_price_id"):
        raise HTTPException(400, f"Plan {plan_id} has no Stripe price configured")

    customer_id = stripe_adapter.create_or_get_customer(
        tenant_id=user["tenant_id"],
        email=user["email"],
    )
    base = str(request.base_url).rstrip("/")
    success_url = body.get("success_url") or f"{base}/?billing=success"
    cancel_url = body.get("cancel_url") or f"{base}/?billing=cancelled"

    session = stripe_adapter.create_checkout_session(
        customer_id=customer_id,
        price_id=plan["stripe_price_id"],
        success_url=success_url,
        cancel_url=cancel_url,
        tenant_id=user["tenant_id"],
    )
    return session


@router.post("/portal")
async def open_portal(request: Request, user: dict = Depends(get_current_user)):
    from .. import db_billing

    if not stripe_adapter.is_configured():
        raise HTTPException(503, "Stripe not configured")
    sub = db_billing.get_active_subscription(user["tenant_id"])
    if not sub or not sub.get("provider_customer_id"):
        raise HTTPException(404, "No active subscription")
    base = str(request.base_url).rstrip("/")
    return_url = f"{base}/?billing=portal-return"
    url = stripe_adapter.create_portal_session(sub["provider_customer_id"], return_url)
    return {"url": url}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="Stripe-Signature"),
):
    from .. import db_billing

    payload = await request.body()
    try:
        event = stripe_adapter.verify_webhook(payload, stripe_signature or "")
    except Exception as e:
        logger.exception("webhook verify failed")
        raise HTTPException(400, f"Webhook signature verification failed: {e}")

    result = stripe_adapter.handle_event(event)
    if not result.get("handled"):
        return {"received": True, "ignored": result["event_type"]}

    tenant_id = result.get("tenant_id")
    if not tenant_id:
        return {"received": True, "no_tenant": True}

    et = result["event_type"]

    if et in ("customer.subscription.created", "customer.subscription.updated"):
        existing = db_billing.get_subscription_by_provider_id(result["subscription_id"])
        fields: dict = {
            "plan_id": result.get("plan_id") or "free",
            "status": result["status"],
            "provider_customer_id": result.get("customer_id"),
            "cancel_at_period_end": result.get("cancel_at_period_end", False),
        }
        if result.get("current_period_start"):
            fields["current_period_start"] = datetime.fromtimestamp(
                result["current_period_start"], tz=tz.utc
            )
        if result.get("current_period_end"):
            fields["current_period_end"] = datetime.fromtimestamp(
                result["current_period_end"], tz=tz.utc
            )
        if result.get("trial_end"):
            fields["trial_end"] = datetime.fromtimestamp(result["trial_end"], tz=tz.utc)

        if existing:
            db_billing.update_subscription(existing["id"], **fields)
        else:
            db_billing.create_subscription(
                tenant_id=tenant_id,
                payment_provider="stripe",
                provider_subscription_id=result["subscription_id"],
                **fields,
            )

    elif et == "customer.subscription.deleted":
        existing = db_billing.get_subscription_by_provider_id(result["subscription_id"])
        if existing:
            db_billing.cancel_subscription(existing["id"], immediate=True)

    return {"received": True, "handled": True, "event_type": et}
