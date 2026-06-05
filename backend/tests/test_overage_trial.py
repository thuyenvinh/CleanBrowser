"""Tests for the subscription-status gate on :func:`emit_overage` (Bug C3).

Before the fix, ``emit_overage`` checked only ``plan.allow_overage`` before
persisting a billable event. A tenant on a trialing or past-due subscription
could therefore accrue Stripe usage records during their free window — which
both violates the trial contract and risks surprise bills on a dunning sub.

The fix re-fetches the subscription inside ``emit_overage`` and short-circuits
when the status is anything other than ``"active"`` (or when no sub exists at
all). These tests pin that behaviour by patching
``backend.db_billing.get_active_subscription`` and asserting we never reach the
``record_overage_event`` insert path.
"""

from __future__ import annotations

import pytest

from backend import db_billing
from backend.billing import overage


# A sentinel that fails the test if anything in ``emit_overage`` reaches the
# real DB-insert helper — the whole point of the gate is that non-active subs
# never get this far.
def _explode_if_called(**kwargs):  # pragma: no cover — failure-only path
    raise AssertionError(
        f"record_overage_event should not be called for non-active sub: {kwargs}"
    )


def test_emit_overage_skips_no_subscription(monkeypatch):
    """No subscription row at all → no billable event."""
    monkeypatch.setattr(db_billing, "get_active_subscription", lambda t: None)
    monkeypatch.setattr(db_billing, "record_overage_event", _explode_if_called)

    result = overage.emit_overage(
        tenant_id="t1", resource="automation_minutes", delta=10
    )
    assert result is None


def test_emit_overage_skips_trialing(monkeypatch):
    """Trialing subs must never be charged overage (free trial contract)."""
    monkeypatch.setattr(
        db_billing,
        "get_active_subscription",
        lambda t: {"id": "s1", "status": "trialing", "plan_id": "pro"},
    )
    monkeypatch.setattr(db_billing, "record_overage_event", _explode_if_called)

    result = overage.emit_overage(
        tenant_id="t1", resource="automation_minutes", delta=10
    )
    assert result is None


def test_emit_overage_skips_past_due(monkeypatch):
    """Past-due dunning subs are paused, not billed for more overage."""
    monkeypatch.setattr(
        db_billing,
        "get_active_subscription",
        lambda t: {"id": "s1", "status": "past_due", "plan_id": "pro"},
    )
    monkeypatch.setattr(db_billing, "record_overage_event", _explode_if_called)

    result = overage.emit_overage(
        tenant_id="t1", resource="automation_minutes", delta=10
    )
    assert result is None


def test_emit_overage_proceeds_for_active(monkeypatch):
    """Active sub with ``allow_overage=True`` must reach the persist path.

    We mock ``record_overage_event`` to capture the call rather than hit the
    real DB — this test asserts behaviour of the gate, not the SQL layer.
    """
    monkeypatch.setattr(
        db_billing,
        "get_active_subscription",
        lambda t: {"id": "s1", "status": "active", "plan_id": "pro"},
    )
    monkeypatch.setattr(
        db_billing,
        "get_plan",
        lambda p: {
            "id": "pro",
            "allow_overage": True,
            "overage_price_per_minute_cents": 5,
        },
    )

    captured: list[dict] = []

    def fake_insert(**kwargs):
        captured.append(kwargs)
        return {"id": "e1", **kwargs}

    monkeypatch.setattr(db_billing, "record_overage_event", fake_insert)

    result = overage.emit_overage(
        tenant_id="t1", resource="automation_minutes", delta=10
    )

    assert result is not None
    assert result["id"] == "e1"
    assert len(captured) == 1
    call = captured[0]
    assert call["tenant_id"] == "t1"
    assert call["subscription_id"] == "s1"
    assert call["resource"] == "automation_minutes"
    assert call["units"] == 10
    # Unit price snapshotted from the plan at event time.
    assert call["unit_price_cents"] == 5
