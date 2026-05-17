"""ClickHouse client for audit log dual-write.

Configure via env:
  CLICKHOUSE_URL — clickhouse://user:pass@host:9000/dbname  (or http://host:8123)
  CLICKHOUSE_TABLE — defaults to 'audit_logs'

Phase 7 phase 2: writes happen synchronously inside the audit middleware
(fire-and-forget). Production should batch via a queue (Redis/Kafka) — see
docs/CLICKHOUSE.md for the recommended deployment topology.
"""
from __future__ import annotations
import json, logging, os, threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_client = None
_lock = threading.Lock()
_SCHEMA_CREATED = False

def is_configured() -> bool:
    return bool(os.environ.get("CLICKHOUSE_URL"))

def _get_client():
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is not None:
            return _client
        try:
            from clickhouse_driver import Client
        except ImportError as e:
            logger.warning("clickhouse_driver not installed: %s", e)
            return None
        try:
            url = os.environ["CLICKHOUSE_URL"]
            _client = Client.from_url(url)
            return _client
        except Exception:
            logger.exception("ClickHouse connection failed")
            return None

_DDL = """
CREATE TABLE IF NOT EXISTS {table} (
  id UUID,
  tenant_id Nullable(UUID),
  actor_user_id Nullable(UUID),
  action LowCardinality(String),
  resource_type Nullable(String),
  resource_id Nullable(String),
  ip Nullable(String),
  user_agent Nullable(String),
  status LowCardinality(String),
  payload String,                    -- JSON serialized
  ts DateTime64(3, 'UTC')
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(ts)
ORDER BY (tenant_id, ts, id)
TTL ts + INTERVAL 365 DAY DELETE     -- 1-year retention; adjust per compliance need
"""

def ensure_schema() -> None:
    """Create the audit_logs table if missing. Safe to call multiple times."""
    global _SCHEMA_CREATED
    if _SCHEMA_CREATED:
        return
    client = _get_client()
    if client is None:
        return
    table = os.environ.get("CLICKHOUSE_TABLE", "audit_logs")
    try:
        client.execute(_DDL.format(table=table))
        _SCHEMA_CREATED = True
        logger.info("ClickHouse audit schema ensured (table=%s)", table)
    except Exception:
        logger.exception("ClickHouse ensure_schema failed")

def write(
    id: str,
    action: str,
    tenant_id: str | None = None,
    actor_user_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    status: str = "success",
    payload: dict | None = None,
    ts: datetime | None = None,
) -> bool:
    """Insert one audit event into ClickHouse. Returns True on success.
    Never raises — audit failures must not break the request flow."""
    client = _get_client()
    if client is None:
        return False
    ensure_schema()
    table = os.environ.get("CLICKHOUSE_TABLE", "audit_logs")
    row = {
        "id": id,
        "tenant_id": tenant_id,
        "actor_user_id": actor_user_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "ip": ip,
        "user_agent": user_agent,
        "status": status,
        "payload": json.dumps(payload or {}),
        "ts": ts or datetime.now(timezone.utc),
    }
    try:
        client.execute(f"INSERT INTO {table} VALUES", [row])
        return True
    except Exception:
        logger.exception("ClickHouse audit insert failed")
        return False

def query_for_tenant(tenant_id: str, limit: int = 100) -> list[dict]:
    """Helper for admin UI — query recent events for a tenant."""
    client = _get_client()
    if client is None:
        return []
    table = os.environ.get("CLICKHOUSE_TABLE", "audit_logs")
    rows = client.execute(
        f"SELECT id, tenant_id, actor_user_id, action, resource_type, resource_id, "
        f"ip, user_agent, status, payload, ts FROM {table} "
        f"WHERE tenant_id = %(t)s ORDER BY ts DESC LIMIT %(l)s",
        {"t": tenant_id, "l": limit},
        with_column_types=False,
    )
    cols = ["id", "tenant_id", "actor_user_id", "action", "resource_type", "resource_id",
            "ip", "user_agent", "status", "payload", "ts"]
    return [dict(zip(cols, r)) for r in rows]
