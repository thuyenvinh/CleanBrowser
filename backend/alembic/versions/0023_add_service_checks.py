"""add service_checks for self-hosted uptime tracking

Phase 5 + 7 follow-up — backs the public ``/status`` page. The
``status_worker`` background task pings internal endpoints every 60s and
records the outcome in this table; the read side
(``/api/status/public``) aggregates rows into rolling uptime
percentages and a recent-incidents feed.

Schema
------
* ``service_checks`` — one row per ping. Columns:

  * ``id`` (BIGSERIAL PRIMARY KEY) — monotonic insertion id. A bigserial
    rather than UUID because we expect ~1440 rows/day per service and a
    short integer keeps the index slim; ``ts DESC`` is the dominant
    access pattern, not lookup-by-id.
  * ``service_name`` (TEXT NOT NULL) — logical service id
    (``'api'``, ``'auth'``, ``'browser_launch'``…). Free-form so adding
    new probes never requires a migration.
  * ``status`` (TEXT NOT NULL) — ``'ok'`` | ``'degraded'`` | ``'down'``.
    Stored as text (not an enum) so future status values don't require a
    schema bump — the worker / read code is the source of truth.
  * ``latency_ms`` (INTEGER, nullable) — round-trip from the probe
    perspective. NULL when the probe never got a response (``down``).
  * ``error_message`` (TEXT, nullable) — short ``"{ExcType}: {msg}"``
    on failure, NULL on success. Truncated by the worker before insert.
  * ``ts`` (TIMESTAMPTZ NOT NULL DEFAULT now()) — wall-clock of the
    probe. Indexed DESC because every aggregator reads "the most recent
    N hours / last N rows", never a random middle slice.

* ``ix_service_checks_service_ts`` — composite ``(service_name, ts
  DESC)`` index. Matches the WHERE + ORDER BY of every uptime / chart
  query so they run as one-shot index range scans instead of seq-scanning
  the whole history. Without this the read path degrades to O(N) the
  moment ``cleanup_old`` falls behind.

RLS
---
The table intentionally has NO ``tenant_id`` column and NO row-level
security policy: monitoring is global to the install (one CloakBrowser
instance has one set of services, not one per tenant), and the public
status feed must be readable by un-authenticated visitors. The
``status_worker`` writes under :func:`backend.middleware_rls.system_context`
so the bypass sentinel is in effect, but no policy actually gates this
table — keeping it out of the RLS regime mirrors how
``proxy_health_history``-style observability tables are typically
handled.

Revision ID: 0023_add_service_checks
Revises: 0022_add_overage_subscription_item
Create Date: 2026-05-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023_add_service_checks"
down_revision: Union[str, Sequence[str], None] = "0022_add_overage_subscription_item"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_checks",
        sa.Column(
            "id",
            sa.BigInteger(),
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("service_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "ts",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Composite index — (service_name, ts DESC) matches every read query
    # (uptime aggregates + chart slices + incident scan). Index creation
    # uses raw SQL because Alembic's ``create_index`` doesn't expose the
    # per-column DESC modifier.
    op.execute(
        "CREATE INDEX ix_service_checks_service_ts "
        "ON service_checks (service_name, ts DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_service_checks_service_ts")
    op.drop_table("service_checks")
