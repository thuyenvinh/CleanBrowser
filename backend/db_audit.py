"""Audit log data layer.

This module is the single write/read path for the ``audit_logs`` table
introduced in migration ``0004_add_audit_logs``. It mirrors the style of
:mod:`backend.database` and :mod:`backend.db_auth` — synchronous psycopg2 on
top of :func:`backend.database.get_db`, returning plain ``dict`` rows.

Design notes:
    * :func:`write` is intentionally *swallowing*: an audit failure must never
      break the user-visible request flow. Errors are logged via
      :mod:`logging` at WARNING level so they show up in observability but do
      not propagate. The trade-off is that we may silently miss audit rows on
      DB outage; the alternative — failing the request — is worse because it
      turns audit into an availability dependency for every mutation.
    * Reads (``list_for_*``) DO raise on error: callers are admin endpoints
      that should surface DB issues to the operator.

See ``docs/ARCHITECTURE`` §2.2 / §2.9.
"""

from __future__ import annotations

import datetime
import json
import logging
import uuid
from typing import Any

import psycopg2.extras

from .database import get_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for key, val in list(out.items()):
        if isinstance(val, uuid.UUID):
            out[key] = str(val)
        elif isinstance(val, datetime.datetime):
            out[key] = val.isoformat()
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write(
    action: str,
    tenant_id: str | None = None,
    actor_user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    status: str = "success",
    payload: dict | None = None,
) -> None:
    """Append a row to ``audit_logs``.

    Never raises. On any error (connection failure, serialisation issue, ...)
    a warning is logged and the call returns silently — audit must not break
    the request flow that invoked it.

    ``action`` follows a ``<resource>.<verb>`` dotted convention, e.g.
    ``user.signup``, ``user.login``, ``profile.launch``, ``workspace.invite``.
    """
    try:
        audit_id = str(uuid.uuid4())
        payload_json = json.dumps(payload) if payload is not None else None
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO audit_logs (
                        id, tenant_id, actor_user_id, action,
                        resource_type, resource_id, ip, user_agent,
                        status, payload
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)""",
                    (
                        audit_id,
                        tenant_id,
                        actor_user_id,
                        action,
                        resource_type,
                        resource_id,
                        ip,
                        user_agent,
                        status,
                        payload_json,
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 — see module docstring
        logger.warning(
            "audit write failed action=%s tenant=%s actor=%s err=%s",
            action,
            tenant_id,
            actor_user_id,
            exc,
        )


def list_for_tenant(
    tenant_id: str,
    limit: int = 100,
    offset: int = 0,
    action_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Return audit rows for a tenant, newest first.

    ``action_filter`` is a substring match (case-sensitive) on the ``action``
    column — useful for filtering "everything starting with ``user.``" without
    pulling the full result set client-side.
    """
    sql = "SELECT * FROM audit_logs WHERE tenant_id = %s"
    params: list[Any] = [tenant_id]
    if action_filter:
        sql += " AND action LIKE %s"
        params.append(f"%{action_filter}%")
    sql += " ORDER BY ts DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [_row_to_dict(r) for r in cur.fetchall()]  # type: ignore[misc]


def list_for_user(
    user_id: str,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return audit rows where ``actor_user_id == user_id``, newest first."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM audit_logs
                   WHERE actor_user_id = %s
                   ORDER BY ts DESC
                   LIMIT %s OFFSET %s""",
                (user_id, limit, offset),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]  # type: ignore[misc]


def migrate_to_clickhouse(batch_size: int = 1000) -> int:
    """One-shot tool: copy existing Postgres audit_logs → ClickHouse.
    Returns rows migrated. Idempotent only if ClickHouse table is empty."""
    from . import audit_clickhouse
    if not audit_clickhouse.is_configured():
        raise RuntimeError("CLICKHOUSE_URL not configured")
    audit_clickhouse.ensure_schema()
    total = 0
    offset = 0
    while True:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM audit_logs ORDER BY ts LIMIT %s OFFSET %s",
                    (batch_size, offset),
                )
                rows = cur.fetchall()
        if not rows:
            break
        for r in rows:
            audit_clickhouse.write(
                id=str(r["id"]),
                action=r["action"],
                tenant_id=str(r["tenant_id"]) if r.get("tenant_id") else None,
                actor_user_id=str(r["actor_user_id"]) if r.get("actor_user_id") else None,
                resource_type=r.get("resource_type"),
                resource_id=r.get("resource_id"),
                ip=r.get("ip"),
                user_agent=r.get("user_agent"),
                status=r.get("status", "success"),
                payload=r.get("payload"),
                ts=r.get("ts"),
            )
        total += len(rows)
        offset += batch_size
        print(f"migrated {total} rows...")
    return total
