"""Tests for status-page uptime helpers (status worker / public status).

Targets :mod:`backend.db_status` — record_check, uptime_percentage,
list_recent_incidents, cleanup_old. Some tests bypass ``record_check``
and INSERT directly so they can backdate the ``ts`` column (record_check
always stamps ``now()``).
"""
from __future__ import annotations

import uuid

from backend import db_status
from backend.database import get_db


def _svc(label: str) -> str:
    """Per-test unique service name — ``service_checks`` survives TRUNCATE."""
    return f"{label}-{uuid.uuid4().hex[:8]}"


def _insert_check(service: str, status: str, ts_sql: str, latency: int | None = None) -> None:
    """Direct INSERT so we can control the ``ts`` value precisely.

    ``ts_sql`` is a SQL fragment evaluated server-side, e.g.
    ``"now() - interval '5 minutes'"``. Keeps the test's time math in
    Postgres so we don't fight client-vs-server clock skew.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO service_checks (service_name, status, latency_ms, ts) "
                f"VALUES (%s, %s, %s, {ts_sql})",
                (service, status, latency),
            )
        conn.commit()


def test_record_check_inserts_row(tmp_db):
    """``record_check`` writes a row visible to subsequent reads.

    ``service_checks`` is intentionally NOT in the per-test TRUNCATE list
    (its retention is bounded by ``cleanup_old`` instead), so the test
    uses a uuid-suffixed service name to isolate from anything other
    tests / a prior pytest session may have written.
    """
    import uuid as _uuid
    svc = f"api-{_uuid.uuid4().hex[:8]}"
    db_status.record_check(svc, "ok", latency_ms=50)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT service_name, status, latency_ms "
                "FROM service_checks WHERE service_name = %s",
                (svc,),
            )
            rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0] == (svc, "ok", 50)


def test_uptime_percentage_all_ok_is_100(tmp_db):
    """All-ok checks → 100% uptime."""
    svc = _svc("svc-ok")
    for _ in range(5):
        db_status.record_check(svc, "ok", latency_ms=20)
    assert db_status.uptime_percentage(svc, hours=24) == 100.0


def test_uptime_percentage_one_failure_in_ten(tmp_db):
    """1 / 10 failed → 90% uptime."""
    svc = _svc("svc-mixed")
    for _ in range(9):
        db_status.record_check(svc, "ok", latency_ms=20)
    db_status.record_check(svc, "down", latency_ms=None, error_message="boom")
    pct = db_status.uptime_percentage(svc, hours=24)
    assert abs(pct - 90.0) < 0.001


def test_list_recent_incidents_excludes_ok(tmp_db):
    """Only ``status != 'ok'`` rows surface as incidents."""
    svc = _svc("svc-inc")
    db_status.record_check(svc, "ok", latency_ms=20)
    db_status.record_check(svc, "down", error_message="timeout")
    incidents = db_status.list_recent_incidents(hours=24, service_name=svc)
    assert len(incidents) == 1
    assert incidents[0]["service_name"] == svc
    assert incidents[0]["status"] == "down"
    assert incidents[0]["error_message"] == "timeout"


def test_cleanup_old_removes_aged_rows(tmp_db):
    """``cleanup_old(days=30)`` deletes rows older than the window, keeps recent ones.

    Scoped by service name so any rows other tests left in the table can't
    skew the ``deleted == 1`` assertion. The cleanup helper itself runs
    table-wide, but we only assert on the per-service row count after.
    """
    svc = _svc("svc-clean")
    # Insert one ancient row (40 days ago) and one fresh row.
    _insert_check(svc, "ok", "now() - interval '40 days'", latency=10)
    _insert_check(svc, "ok", "now()", latency=10)

    # Capture this service's row count before/after — cleanup_old returns
    # the global delete count which may include other tests' aged rows,
    # so we assert on our own service's delta instead.
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM service_checks WHERE service_name = %s",
                (svc,),
            )
            before = cur.fetchone()[0]
    assert before == 2

    db_status.cleanup_old(days=30)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM service_checks WHERE service_name = %s",
                (svc,),
            )
            remaining = cur.fetchone()[0]
    assert remaining == 1
