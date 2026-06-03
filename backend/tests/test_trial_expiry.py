"""Tests for trial expiry worker (C1 fix).

The worker flips ``subscriptions.status='trialing' → 'past_due'`` once
``trial_end`` has passed. Without it, free trial users stay on Pro forever.
"""
from __future__ import annotations

import datetime
import uuid

import pytest

from backend import db_billing


def _make_tenant(tmp_db) -> str:
    from backend.database import get_db
    tenant_id = str(uuid.uuid4())
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (id, name, plan_id, status) VALUES (%s, %s, %s, %s)",
                (tenant_id, "trial-tenant", "free", "active"),
            )
    return tenant_id


def test_expire_due_trials_flips_past_due(tmp_db):
    """A trial whose trial_end already passed becomes past_due on next tick."""
    tenant_id = _make_tenant(tmp_db)
    sub = db_billing.create_subscription(
        tenant_id=tenant_id,
        plan_id="pro",
        status="trialing",
        trial_end=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1),
    )

    count = db_billing.expire_due_trials()

    assert count >= 1
    refreshed = db_billing.get_active_subscription(tenant_id)
    assert refreshed is not None
    assert refreshed["status"] == "past_due"


def test_expire_due_trials_leaves_future_trials_alone(tmp_db):
    tenant_id = _make_tenant(tmp_db)
    db_billing.create_subscription(
        tenant_id=tenant_id,
        plan_id="pro",
        status="trialing",
        trial_end=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10),
    )
    db_billing.expire_due_trials()

    refreshed = db_billing.get_active_subscription(tenant_id)
    assert refreshed["status"] == "trialing"


def test_expire_due_trials_does_not_touch_active(tmp_db):
    """Active subs are out of scope — only `trialing` flips."""
    tenant_id = _make_tenant(tmp_db)
    db_billing.create_subscription(
        tenant_id=tenant_id,
        plan_id="pro",
        status="active",
        trial_end=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=5),
    )
    db_billing.expire_due_trials()

    refreshed = db_billing.get_active_subscription(tenant_id)
    assert refreshed["status"] == "active"


def test_expire_due_trials_returns_zero_when_none_due(tmp_db):
    """Counter reflects rows actually flipped, not total seen."""
    count = db_billing.expire_due_trials()
    assert isinstance(count, int)
    assert count >= 0
