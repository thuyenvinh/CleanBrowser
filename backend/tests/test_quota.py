"""Unit tests for :mod:`backend.quota`.

The module's only external collaborator is :mod:`backend.db_billing`,
which HHH is building in the same wave and isn't on disk yet. We work
around that with two tricks:

1. ``monkeypatch.setattr("backend.db_billing.<fn>", ..., raising=False)``
   stubs the names without requiring the real module to import — the
   ``raising=False`` flag lets us patch attributes on a placeholder.
2. We install a minimal ``backend.db_billing`` stub via ``sys.modules``
   in a session fixture so :func:`backend.quota.check_quota`'s lazy
   ``from backend import db_billing`` finds *something* to import.

This keeps the test self-contained: JJJ can land the quota module
ahead of HHH's db_billing implementation without breaking the suite.
"""

from __future__ import annotations

import sys
import types

import pytest

from backend import quota

# Ensure ``backend.db_billing`` is importable as an attribute of the
# ``backend`` package *before* any test runs. Two reasons:
#
# 1. If HHH's real module is on disk, importing it eagerly binds
#    ``backend.db_billing`` so ``monkeypatch.setattr("backend.db_billing.<fn>")``
#    can resolve the dotted path without tripping the "no attribute
#    db_billing" walker error pytest's resolver raises for unbound
#    submodules.
# 2. If it's *not* on disk yet (JJJ landing ahead of HHH), the
#    ``ImportError`` is caught and we install a minimal stub module so
#    the lazy ``from backend import db_billing`` inside
#    :func:`backend.quota.check_quota` still finds something.
try:
    from backend import db_billing as _real_db_billing  # noqa: F401
except ImportError:
    _stub = types.ModuleType("backend.db_billing")
    _stub.get_tenant_limits = lambda _tid: {}  # type: ignore[attr-defined]
    _stub.get_tenant_usage = lambda _tid: {}  # type: ignore[attr-defined]
    _stub.set_counter = lambda *a, **kw: None  # type: ignore[attr-defined]
    _stub.increment_counter = lambda *a, **kw: None  # type: ignore[attr-defined]
    _stub.update_peak = lambda *a, **kw: None  # type: ignore[attr-defined]
    sys.modules["backend.db_billing"] = _stub
    import backend as _backend_pkg

    _backend_pkg.db_billing = _stub  # type: ignore[attr-defined]


def test_check_quota_unlimited(monkeypatch: pytest.MonkeyPatch):
    """A ``None`` plan limit means unlimited — usage is irrelevant."""
    monkeypatch.setattr(
        "backend.db_billing.get_tenant_limits",
        lambda _: {"max_profiles": None},
        raising=False,
    )
    monkeypatch.setattr(
        "backend.db_billing.get_tenant_usage",
        lambda _: {"profile_count": 9999},
        raising=False,
    )
    r = quota.check_quota("t1", "create_profile")
    assert r.allowed is True
    assert r.limit is None


def test_check_quota_within_limit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "backend.db_billing.get_tenant_limits",
        lambda _: {"max_profiles": 10},
        raising=False,
    )
    monkeypatch.setattr(
        "backend.db_billing.get_tenant_usage",
        lambda _: {"profile_count": 5},
        raising=False,
    )
    r = quota.check_quota("t1", "create_profile")
    assert r.allowed is True
    assert r.limit == 10
    assert r.current == 5


def test_check_quota_exceeded(monkeypatch: pytest.MonkeyPatch):
    """At-cap is treated as denial — the next action would push us over."""
    monkeypatch.setattr(
        "backend.db_billing.get_tenant_limits",
        lambda _: {"max_profiles": 10},
        raising=False,
    )
    monkeypatch.setattr(
        "backend.db_billing.get_tenant_usage",
        lambda _: {"profile_count": 10},
        raising=False,
    )
    r = quota.check_quota("t1", "create_profile")
    assert r.allowed is False
    assert "10/10" in r.reason


def test_raise_if_exceeded_emits_402():
    """The HTTPException carries the 402 status and a structured detail dict."""
    from fastapi import HTTPException

    r = quota.QuotaCheckResult(
        allowed=False, limit=10, current=11, reason="test reason"
    )
    with pytest.raises(HTTPException) as ei:
        r.raise_if_exceeded()
    assert ei.value.status_code == 402
    assert isinstance(ei.value.detail, dict)
    assert ei.value.detail["error"] == "quota_exceeded"
    assert ei.value.detail["limit"] == 10
    assert ei.value.detail["current"] == 11


def test_raise_if_exceeded_noop_when_allowed():
    """Allowed results must not raise — they're the hot path."""
    quota.QuotaCheckResult(allowed=True, limit=10, current=5).raise_if_exceeded()


def test_unknown_action_raises():
    """Typos in the action string should surface immediately at the call site."""
    with pytest.raises(ValueError):
        quota.check_quota("t1", "bogus_action")  # type: ignore[arg-type]


def test_create_workspace_no_field_passes():
    """Actions without a configured plan field default to allowed."""
    r = quota.check_quota("t1", "create_workspace")
    assert r.allowed is True
    assert r.limit is None


def test_check_quota_missing_usage_field(monkeypatch: pytest.MonkeyPatch):
    """A missing usage_field key in the dict should be treated as 0."""
    monkeypatch.setattr(
        "backend.db_billing.get_tenant_limits",
        lambda _: {"max_profiles": 10},
        raising=False,
    )
    monkeypatch.setattr(
        "backend.db_billing.get_tenant_usage",
        lambda _: {},  # no profile_count key at all
        raising=False,
    )
    r = quota.check_quota("t1", "create_profile")
    assert r.allowed is True
    assert r.current == 0


def test_record_usage_unknown_action_is_noop():
    """Unknown actions silently no-op — never propagate to caller."""
    # No exception, no DB call (the stubs would no-op anyway).
    quota.record_usage("t1", "bogus_action", 1)  # type: ignore[arg-type]


def test_record_usage_swallows_errors(monkeypatch: pytest.MonkeyPatch):
    """A failing increment must not break the surrounding user action."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(
        "backend.db_billing.increment_counter", boom, raising=False
    )
    # Should log and return cleanly.
    quota.record_usage("t1", "run_automation", 5)


def test_record_usage_run_automation_calls_increment(
    monkeypatch: pytest.MonkeyPatch,
):
    """``run_automation`` is the accumulate path — delegates to increment_counter."""
    seen: dict[str, object] = {}

    def fake_increment(tid, field, delta):
        seen["tid"] = tid
        seen["field"] = field
        seen["delta"] = delta

    monkeypatch.setattr(
        "backend.db_billing.increment_counter", fake_increment, raising=False
    )
    quota.record_usage("t1", "run_automation", 7)
    assert seen == {
        "tid": "t1",
        "field": "automation_minutes_used",
        "delta": 7,
    }
