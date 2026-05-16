"""Billing endpoints — Stripe checkout, customer portal, webhook."""
from __future__ import annotations

import logging
from datetime import datetime, timezone as tz

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..billing import stripe_adapter, vnpay_adapter
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


@router.post("/vnpay/checkout")
async def vnpay_checkout(
    body: dict, request: Request, user: dict = Depends(get_current_user)
):
    """body: {plan_id}. Creates VNPay payment URL for one-time payment."""
    from .. import db_billing

    if not vnpay_adapter.is_configured():
        raise HTTPException(503, "VNPay not configured")
    plan_id = body.get("plan_id")
    plan = db_billing.get_plan(plan_id) if plan_id else None
    if not plan:
        raise HTTPException(404, "Plan not found")
    # Approx convert USD cents -> VND (1 USD ~= 25,000 VND).
    # Production: use real FX or per-plan VND price.
    amount_vnd = int(plan["price_cents"] * 250)  # cents * 250 = USD * 25000
    if amount_vnd <= 0:
        raise HTTPException(400, "Free plan does not require payment")
    base = str(request.base_url).rstrip("/")
    result = vnpay_adapter.build_checkout_url(
        tenant_id=user["tenant_id"],
        plan_id=plan["id"],
        amount_vnd=amount_vnd,
        order_info=f"Subscribe to {plan['name']} ({user['tenant_id']})",
        return_url=f"{base}/api/billing/vnpay/return",
        client_ip=request.client.host if request.client else "127.0.0.1",
    )
    # Persist a pending subscription so callback can find it.
    # status='trialing' is used as a "pending" placeholder until the callback
    # confirms; a dedicated 'pending' status would land in a later wave.
    db_billing.create_subscription(
        tenant_id=user["tenant_id"],
        plan_id=plan["id"],
        status="trialing",
        payment_provider="vnpay",
        provider_subscription_id=result["vnp_TxnRef"],
    )
    return result


@router.get("/vnpay/return")
async def vnpay_return(request: Request):
    from .. import db_billing

    params = dict(request.query_params)
    ok, txn_ref = vnpay_adapter.verify_callback(params)
    if not ok:
        return RedirectResponse(
            f"/?billing=vnpay-failed&ref={txn_ref}", status_code=302
        )
    # Find subscription by provider_subscription_id and activate
    sub = db_billing.get_subscription_by_provider_id(txn_ref)
    if sub:
        db_billing.update_subscription(sub["id"], status="active")
    return RedirectResponse(f"/?billing=success&ref={txn_ref}", status_code=302)
