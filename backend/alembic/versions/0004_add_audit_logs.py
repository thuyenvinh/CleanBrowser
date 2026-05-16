"""add audit_logs table

Phase 1 audit trail. ``audit_logs`` records every meaningful mutation (signup,
login, profile launch, member changes, ...) so operators can answer "who did
what, when, from where". See ``docs/ARCHITECTURE`` §2.2 (schema) and §2.9
(observability).

Storage choice — Postgres now, ClickHouse later:
    The architecture doc targets ClickHouse for audit (Phase 3+) because the
    table will eventually hold millions of rows per tenant and we want
    columnar scans for the admin search UI. For Phase 1 we keep it in
    Postgres next to the other operational data — single write path, single
    backup, no extra infra to operate. Migrating to ClickHouse later is a
    pure ETL: the column set defined here maps 1:1.

Why no foreign keys to ``tenants`` / ``users``:
    Audit must survive deletion of the actor or tenant — otherwise we lose
    the history of how that entity behaved, which defeats the purpose. The
    columns are typed as UUID so the values stay queryable, but Postgres
    will not cascade-delete or block deletion based on audit rows.

Indexes:
    * ``ix_audit_logs_tenant_ts`` — admin UI "recent activity for tenant X".
    * ``ix_audit_logs_actor_ts`` — "what did user X do recently".
    * ``ix_audit_logs_action``   — coarse filter, e.g. all ``user.login``.

Revision ID: 0004_add_audit_logs
Revises: 0003_add_auth_tables
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_add_audit_logs"
down_revision: Union[str, Sequence[str], None] = "0003_add_auth_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        # No FK: audit rows must outlive their tenant/user. See module docstring.
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=True),
        sa.Column("resource_id", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "ts",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_audit_logs_tenant_ts",
        "audit_logs",
        ["tenant_id", sa.text("ts DESC")],
    )
    op.create_index(
        "ix_audit_logs_actor_ts",
        "audit_logs",
        ["actor_user_id", sa.text("ts DESC")],
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_ts", table_name="audit_logs")
    op.drop_index("ix_audit_logs_tenant_ts", table_name="audit_logs")
    op.drop_table("audit_logs")
