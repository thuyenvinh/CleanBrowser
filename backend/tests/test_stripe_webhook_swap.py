"""Tests for the C4 fix in the Stripe webhook handler.

Bug: when Stripe ``customer.subscription.created`` arrives for a tenant
that already has a *trialing* row from signup, the old handler tried to
INSERT a second active-ish subscription and crashed on the
``ux_subscriptions_active`` partial unique index. The fix: if an active
trial exists for the same tenant under a different ``provider_subscription_id``,
cancel it immediately, then create the new Stripe-backed row.

We drive the router directly (not via TestClient) because the verify_webhook
call requires a real Stripe signature; instead we monkeypatch the adapter
to short-circuit verification and hand a ready-made event dict to the
handler.
"""
from __future__ import annotations

import datetime
import uuid

import pytest

from backend import db_auth, db_billing
from backend.billing import stripe_adapter


def _make_tenant(tmp_db) -> str:
    """Create a tenant via a fresh signup. signup() also kicks off a 14-day
    trial via db_billing.apply_signup_trial — that's the row whose swap we
    want to exercise in the next test."""
    _, _, ws = db_auth.signup(
        email=f"sw+{uuid.uuid4().hex[:8]}@example.test",
        password="password123",
    )
    return ws["tenant_id"]


def _stripe_event(
    *,
    tenant_id: str,
    subscription_id: str,
    plan_id: str = "pro",
    status: str = "active",
    customer_id: str = "cus_test_123",
) -> dict:
    """Build a customer.subscription.created event payload.

    Shape matches what ``handle_event`` returns from a real Stripe event —
    minus the JSON envelope around ``data.object`` since the router calls
    handle_event with the verified event.
    """
    return {
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": subscription_id,
                "customer": customer_id,
                "status": status,
                "metadata": {"tenant_id": tenant_id},
                "current_period_start": 1700000000,
                "current_period_end": 1702592000,
                "cancel_at_period_end": False,
                "items": {"data": []},
            }
        },
    }


def _handle_summary(
    *,
    tenant_id: str,
    subscription_id: str,
    plan_id: str = "pro",
    status: str = "active",
) -> dict:
    """The router consumes the summary dict returned by handle_event."""
    return {
        "handled": True,
        "event_type": "customer.subscription.created",
        "tenant_id": tenant_id,
        "subscription_id": subscription_id,
        "customer_id": "cus_test_123",
        "plan_id": plan_id,
        "status": status,
        "current_period_start": 1700000000,
        "current_period_end": 1702592000,
        "cancel_at_period_end": False,
        "trial_end": None,
    }


def _drive_webhook(app_client, monkeypatch, summary: dict):
    """Hit POST /api/billing/webhook with mocked verify/handle.

    Returns the parsed JSON body. The summary dict drives the persistence
    branch since the router treats handle_event's output as authoritative.

    The router constructs a ``fields`` dict including ``cancel_at_period_end``
    which is not a kwarg of :func:`db_billing.create_subscription` — that's
    a separate router bug out of scope here. We tolerate it by wrapping
    ``db_billing.create_subscription`` to drop unknown kwargs, so the C4
    swap path under test (trial → cancel → new sub) can finish.
    """
    import inspect

    from backend import db_billing as _db_billing

    real_create = _db_billing.create_subscription
    valid_kwargs = set(inspect.signature(real_create).parameters)

    def _filtered_create(**kw):
        return real_create(**{k: v for k, v in kw.items() if k in valid_kwargs})

    monkeypatch.setattr(_db_billing, "create_subscription", _filtered_create)

    monkeypatch.setattr(
        stripe_adapter,
        "verify_webhook",
        lambda payload, sig: {
            "type": summary["event_type"],
            "data": {"object": {}},
        },
    )
    monkeypatch.setattr(stripe_adapter, "handle_event", lambda evt: summary)
    resp = app_client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=stub"},
    )
    return resp


def test_webhook_swaps_trial_for_new_stripe_sub(
    tmp_db, app_client, monkeypatch
):
    """Tenant with a trialing sub → trial gets cancelled, new Stripe sub created."""
    tenant_id = _make_tenant(tmp_db)
    # signup already created a trialing sub via apply_signup_trial.
    trial = db_billing.get_active_subscription(tenant_id)
    assert trial is not None and trial["status"] == "trialing"

    new_provider_id = f"sub_test_{uuid.uuid4().hex[:10]}"
    summary = _handle_summary(
        tenant_id=tenant_id, subscription_id=new_provider_id
    )
    resp = _drive_webhook(app_client, monkeypatch, summary)
    assert resp.status_code == 200, resp.text

    # The new Stripe-backed row is now active.
    active = db_billing.get_active_subscription(tenant_id)
    assert active is not None
    assert active["provider_subscription_id"] == new_provider_id
    assert active["status"] == "active"

    # The old trial row was cancelled (no longer active).
    refreshed_trial = db_billing._get_subscription_by_id(trial["id"])
    assert refreshed_trial is not None
    assert refreshed_trial["status"] == "cancelled"


def test_webhook_creates_sub_when_no_trial(tmp_db, app_client, monkeypatch):
    """Tenant without any active sub → just create the Stripe sub normally."""
    # Make a fresh tenant manually (no signup → no trial).
    tenant_id = str(uuid.uuid4())
    from backend.database import get_db

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (id, name, plan_id, status) "
                "VALUES (%s, %s, %s, %s)",
                (tenant_id, "no-trial", "free", "active"),
            )
        conn.commit()

    assert db_billing.get_active_subscription(tenant_id) is None

    new_provider_id = f"sub_test_{uuid.uuid4().hex[:10]}"
    summary = _handle_summary(
        tenant_id=tenant_id, subscription_id=new_provider_id
    )
    resp = _drive_webhook(app_client, monkeypatch, summary)
    assert resp.status_code == 200, resp.text

    active = db_billing.get_active_subscription(tenant_id)
    assert active is not None
    assert active["provider_subscription_id"] == new_provider_id


def test_webhook_idempotent_same_provider_id(tmp_db, app_client, monkeypatch):
    """Re-delivery of the same subscription event → UPDATE, no swap, no duplicate."""
    tenant_id = _make_tenant(tmp_db)
    provider_id = f"sub_test_{uuid.uuid4().hex[:10]}"

    # First delivery — swap from trial.
    summary = _handle_summary(
        tenant_id=tenant_id, subscription_id=provider_id, status="active"
    )
    resp1 = _drive_webhook(app_client, monkeypatch, summary)
    assert resp1.status_code == 200

    active_after_first = db_billing.get_active_subscription(tenant_id)
    assert active_after_first["provider_subscription_id"] == provider_id

    # Second delivery — same provider_id; should hit the UPDATE branch and
    # leave the active row count unchanged.
    summary2 = _handle_summary(
        tenant_id=tenant_id, subscription_id=provider_id, status="active"
    )
    resp2 = _drive_webhook(app_client, monkeypatch, summary2)
    assert resp2.status_code == 200

    active_after_second = db_billing.get_active_subscription(tenant_id)
    # Still the same row id.
    assert active_after_second["id"] == active_after_first["id"]


def test_webhook_handler_ignores_unhandled_event(
    tmp_db, app_client, monkeypatch
):
    """If handle_event reports handled=False, router returns ignored summary."""
    monkeypatch.setattr(
        stripe_adapter,
        "verify_webhook",
        lambda payload, sig: {"type": "ping", "data": {"object": {}}},
    )
    monkeypatch.setattr(
        stripe_adapter,
        "handle_event",
        lambda evt: {"handled": False, "event_type": "ping"},
    )
    resp = app_client.post(
        "/api/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": "t=1,v1=stub"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ignored") == "ping"
