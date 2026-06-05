"""Tests for audit-log writes under RLS + ClickHouse fallback.

* :func:`backend.db_audit.write` must succeed under the system context
  used by background workers, and must tolerate ``tenant_id=None`` (the
  ``audit_logs`` RLS policy explicitly allows NULL so login/signup events
  before a session exists can still be recorded).
* :mod:`backend.audit_clickhouse` must report unconfigured + no-op write
  when ``CLICKHOUSE_URL`` isn't set — production tail-end uses Postgres
  exclusively when no warehouse is wired up.
"""
from __future__ import annotations

import uuid

import pytest

from backend import audit_clickhouse, db_audit
from backend.database import get_db


def test_db_audit_write_under_system_context(tmp_db):
    """write() with all the usual fields succeeds and inserts a row."""
    action = f"test.write.{uuid.uuid4().hex[:8]}"
    db_audit.write(
        action=action,
        tenant_id=None,
        actor_user_id=None,
        resource_type="test",
        resource_id="x",
        status="success",
        payload={"k": "v"},
    )
    # Verify a row landed — RLS policy on audit_logs allows NULL tenant_id.
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE action = %s",
                (action,),
            )
            (count,) = cur.fetchone()
    assert count == 1


def test_db_audit_write_with_null_tenant_does_not_raise(tmp_db):
    """audit_logs RLS allows tenant_id IS NULL — login-attempt rows need it."""
    # The function never raises by contract; verify it returns None and
    # inserts the row even without tenant context.
    action = f"test.null_tenant.{uuid.uuid4().hex[:8]}"
    result = db_audit.write(action=action, tenant_id=None)
    assert result is None  # write returns None unconditionally
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tenant_id FROM audit_logs WHERE action = %s",
                (action,),
            )
            row = cur.fetchone()
    assert row is not None
    assert row[0] is None


def test_db_audit_write_swallows_errors(tmp_db, monkeypatch):
    """write() must never raise — even if the DB call itself blows up."""

    class _Boom:
        def __enter__(self):
            raise RuntimeError("simulated DB outage")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(db_audit, "get_db", lambda: _Boom())
    # Should not raise.
    db_audit.write(action="test.boom")


def test_audit_clickhouse_unconfigured(monkeypatch):
    """is_configured() returns False when CLICKHOUSE_URL is unset."""
    monkeypatch.delenv("CLICKHOUSE_URL", raising=False)
    assert audit_clickhouse.is_configured() is False


def test_audit_clickhouse_write_noop_when_unconfigured(monkeypatch):
    """write() returns False (no-op) when the client cannot be built."""
    monkeypatch.delenv("CLICKHOUSE_URL", raising=False)
    # Reset cached client so _get_client() retries with the cleared env.
    monkeypatch.setattr(audit_clickhouse, "_client", None)
    ok = audit_clickhouse.write(
        id=str(uuid.uuid4()),
        action="test.noop",
    )
    assert ok is False
