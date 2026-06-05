"""Tests for overage skip when subscription is not active (C3 fix).

A trialing user must never be billed for going over plan limits — the relay
worker shouldn't even record the event. This test pins that invariant.
"""
from __future__ import annotations

import pytest

from backend.billing import overage


@pytest.fixture
def patch_billing(monkeypatch):
    """Provide a controllable view of get_active_subscription / get_plan."""

    state: dict = {"sub": None, "plan": None}

    def fake_get_sub(_tenant):
        return state["sub"]

    def fake_get_plan(_plan_id):
        return state["plan"]

    monkeypatch.setattr("backend.db_billing.get_active_subscription", fake_get_sub)
    monkeypatch.setattr("backend.db_billing.get_plan", fake_get_plan)
    # Make accidental progress into a persistence call fail loudly.
    def explode(*_a, **_kw):
        raise AssertionError("record_overage_event must NOT be reached for non-active subs")
    monkeypatch.setattr("backend.billing.overage.record_overage_event", explode, raising=False)

    return state


def test_emit_overage_skips_when_no_subscription(patch_billing):
    patch_billing["sub"] = None
    result = overage.emit_overage(tenant_id="t1", resource="automation_minutes", delta=10)
    assert result is None


def test_emit_overage_skips_trialing(patch_billing):
    patch_billing["sub"] = {"id": "s1", "status": "trialing", "plan_id": "pro"}
    patch_billing["plan"] = {"id": "pro", "allow_overage": True, "overage_price_per_minute_cents": 5}
    result = overage.emit_overage(tenant_id="t1", resource="automation_minutes", delta=10)
    assert result is None


def test_emit_overage_skips_past_due(patch_billing):
    patch_billing["sub"] = {"id": "s1", "status": "past_due", "plan_id": "pro"}
    patch_billing["plan"] = {"id": "pro", "allow_overage": True, "overage_price_per_minute_cents": 5}
    result = overage.emit_overage(tenant_id="t1", resource="automation_minutes", delta=10)
    assert result is None


def test_emit_overage_skips_cancelled(patch_billing):
    patch_billing["sub"] = {"id": "s1", "status": "cancelled", "plan_id": "pro"}
    patch_billing["plan"] = {"id": "pro", "allow_overage": True, "overage_price_per_minute_cents": 5}
    result = overage.emit_overage(tenant_id="t1", resource="automation_minutes", delta=10)
    assert result is None
