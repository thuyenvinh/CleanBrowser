"""Service-checks data layer — uptime tracking for the public status page.

Backs the ``service_checks`` table introduced by migration
``0023_add_service_checks``. Two callers:

* :mod:`backend.status_worker` — pushes one row per probe via
  :func:`record_check` and periodically calls :func:`cleanup_old` to
  bound the table size.
* :mod:`backend.routers.system` — serves ``/api/status/public`` by
  aggregating with :func:`uptime_percentage`,
  :func:`list_recent_incidents` and :func:`list_recent_checks`.

The table has no ``tenant_id`` column / RLS policy (see migration
0023's docstring), so every call here runs unconditionally — callers
still wrap in :func:`backend.middleware_rls.system_context` for
consistency with the rest of the worker code-base, but it is a no-op
for this table.

Design notes
------------
* All public helpers are *synchronous psycopg2* on top of
  :func:`backend.database.get_db`. Mirrors :mod:`backend.db_proxy` —
  the worker is async but runs each DB call in the same event loop
  thread; psycopg2's blocking behaviour is acceptable because the
  call is cheap and runs at most a few times per minute.
* Aggregation lives in SQL (``COUNT(*) FILTER (WHERE status = 'ok')``)
  rather than in Python because pulling every row over the wire just
  to count them would scale linearly with the retention window.
* :func:`list_recent_incidents` groups consecutive non-``ok`` rows
  client-side. Doing it in SQL would require a window function +
  ``DISTINCT ON`` dance that is harder to read for marginal gain; the
  set of incident rows fits in memory by construction (we cleanup
  anything older than 30 days).
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg2.extras

from .database import get_db

logger = logging.getLogger("cloakbrowser.db_status")

# Maximum length we persist for error messages — anything longer is
# noise (full tracebacks belong in the application log, not in a row
# that will be returned to an un-authenticated status page).
_MAX_ERROR_LEN = 500


def record_check(
    service_name: str,
    status: str,
    latency_ms: int | None = None,
    error_message: str | None = None,
) -> None:
    """Insert one probe outcome.

    Swallows DB errors so a transient outage of the metadata DB itself
    can never crash the monitoring worker. The probe loop logs
    separately, so a silent insert failure here is observable upstream.
    """
    if error_message and len(error_message) > _MAX_ERROR_LEN:
        error_message = error_message[:_MAX_ERROR_LEN]
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO service_checks
                           (service_name, status, latency_ms, error_message)
                       VALUES (%s, %s, %s, %s)""",
                    (service_name, status, latency_ms, error_message),
                )
            conn.commit()
    except Exception:
        logger.exception("record_check insert failed for %s", service_name)


def uptime_percentage(service_name: str, hours: int = 24) -> float:
    """``count(status='ok') / count(*) * 100`` over the last ``hours`` hours.

    Returns ``100.0`` if there are zero rows in the window — "no data"
    is treated as "no failures" so a freshly booted install doesn't
    show 0 % uptime before the worker's first tick. The numeric cast
    keeps the result a Python ``float`` regardless of psycopg2 row
    casting.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT
                           COUNT(*) FILTER (WHERE status = 'ok')::float
                               / NULLIF(COUNT(*), 0)::float * 100
                       FROM service_checks
                       WHERE service_name = %s
                         AND ts >= now() - (%s || ' hours')::interval""",
                    (service_name, str(hours)),
                )
                row = cur.fetchone()
        if row is None or row[0] is None:
            return 100.0
        return float(row[0])
    except Exception:
        logger.exception("uptime_percentage failed for %s", service_name)
        return 0.0


def list_recent_incidents(
    hours: int = 168, service_name: str | None = None
) -> list[dict[str, Any]]:
    """Return ``status != 'ok'`` events grouped into consecutive runs.

    Each returned dict carries::

        {
            "service_name": str,
            "status": str,           # the worst status seen in the run
            "started_at": isoformat,
            "ended_at": isoformat,   # = last failed row's ts (NOT recovery)
            "count": int,            # # of failed pings in the run
            "error_message": str | None,  # most recent error in the run
        }

    Grouping logic: a run starts at a failed row whose immediate
    predecessor (per ``service_name`` ordered by ``ts``) was ``ok`` (or
    a different service / nothing). The runs are computed client-side
    after a single ``ORDER BY ts`` fetch — see module docstring for
    why.
    """
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if service_name is None:
                    cur.execute(
                        """SELECT service_name, status, error_message, ts
                           FROM service_checks
                           WHERE ts >= now() - (%s || ' hours')::interval
                             AND status != 'ok'
                           ORDER BY service_name ASC, ts ASC""",
                        (str(hours),),
                    )
                else:
                    cur.execute(
                        """SELECT service_name, status, error_message, ts
                           FROM service_checks
                           WHERE service_name = %s
                             AND ts >= now() - (%s || ' hours')::interval
                             AND status != 'ok'
                           ORDER BY ts ASC""",
                        (service_name, str(hours)),
                    )
                rows = cur.fetchall()
    except Exception:
        logger.exception("list_recent_incidents query failed")
        return []

    incidents: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    # A gap of more than this many seconds between two failed rows for
    # the same service splits them into separate incidents. Matches the
    # 60s tick + some slack — anything bigger means the service
    # recovered (an ``ok`` row was logged) in between.
    GAP_SECONDS = 180

    for row in rows:
        svc = row["service_name"]
        ts = row["ts"]
        if (
            current is not None
            and current["service_name"] == svc
            and (ts - current["_last_ts"]).total_seconds() <= GAP_SECONDS
        ):
            current["ended_at"] = ts.isoformat()
            current["_last_ts"] = ts
            current["count"] += 1
            # Worst-status wins: 'down' > 'degraded'.
            if row["status"] == "down":
                current["status"] = "down"
            if row["error_message"]:
                current["error_message"] = row["error_message"]
        else:
            if current is not None:
                current.pop("_last_ts", None)
                incidents.append(current)
            current = {
                "service_name": svc,
                "status": row["status"],
                "started_at": ts.isoformat(),
                "ended_at": ts.isoformat(),
                "_last_ts": ts,
                "count": 1,
                "error_message": row["error_message"],
            }
    if current is not None:
        current.pop("_last_ts", None)
        incidents.append(current)

    # Most recent first — the status page renders top-down.
    incidents.sort(key=lambda i: i["started_at"], reverse=True)
    return incidents


def list_recent_checks(
    service_name: str, hours: int = 24, limit: int = 1440
) -> list[dict[str, Any]]:
    """Return raw probe rows for charting — ``ts`` / ``status`` / ``latency``.

    The default ``limit=1440`` matches "one tick per minute over 24h",
    so the worker never returns more data than the chart can plot.
    Ordered oldest -> newest because chart libraries expect that
    direction even though we filter via a DESC index.
    """
    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """SELECT ts, status, latency_ms
                       FROM (
                           SELECT ts, status, latency_ms
                           FROM service_checks
                           WHERE service_name = %s
                             AND ts >= now() - (%s || ' hours')::interval
                           ORDER BY ts DESC
                           LIMIT %s
                       ) sub
                       ORDER BY ts ASC""",
                    (service_name, str(hours), limit),
                )
                rows = cur.fetchall()
    except Exception:
        logger.exception("list_recent_checks query failed")
        return []

    return [
        {
            "ts": r["ts"].isoformat(),
            "status": r["status"],
            "latency_ms": r["latency_ms"],
        }
        for r in rows
    ]


def cleanup_old(days: int = 30) -> int:
    """Delete rows older than ``days``. Returns the number of rows removed.

    Called once per 24h by :mod:`backend.status_worker`. We could
    enforce a retention via ``pg_cron`` instead, but doing it from the
    worker keeps the schema portable across managed-Postgres flavours
    that don't ship pg_cron.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """DELETE FROM service_checks
                       WHERE ts < now() - (%s || ' days')::interval""",
                    (str(days),),
                )
                deleted = cur.rowcount or 0
            conn.commit()
        return int(deleted)
    except Exception:
        logger.exception("cleanup_old failed")
        return 0


__all__ = [
    "record_check",
    "uptime_percentage",
    "list_recent_incidents",
    "list_recent_checks",
    "cleanup_old",
]
