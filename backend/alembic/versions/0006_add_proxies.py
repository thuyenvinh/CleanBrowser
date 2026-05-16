"""add proxies table

Phase 2 (task R) — scaffold the workspace-level proxy pool described in
``docs/ARCHITECTURE`` §2.5. Adds a single ``proxies`` table that the API
layer / browser_manager will adopt in a follow-up task. The ``profiles``
table is intentionally NOT touched here — a ``profiles.proxy_id`` column
will land in a separate migration once routes / launch flow are wired.

Credentials (``password_enc``) are stored encrypted with a Fernet key held
by the application process (see :mod:`backend.db_proxy`). The migration
itself is key-agnostic: the column is just opaque TEXT.

Revision ID: 0006_add_proxies
Revises: 0005_profile_workspace_id
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_add_proxies"
down_revision: Union[str, Sequence[str], None] = "0005_profile_workspace_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "proxies",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        # type ∈ {'http','https','socks5'} — validated in the app layer.
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        # Fernet ciphertext (urlsafe base64 TEXT). NULL when the proxy
        # requires no auth.
        sa.Column("password_enc", sa.Text(), nullable=True),
        # provider ∈ {'manual','911','brightdata','smartproxy','iproyal'}.
        sa.Column(
            "provider", sa.Text(), nullable=True,
        ),
        sa.Column("rotation_url", sa.Text(), nullable=True),
        sa.Column("sticky_session", sa.Text(), nullable=True),
        sa.Column("country_code", sa.Text(), nullable=True),
        # status ∈ {'ok','fail','unchecked'} — updated by health check job.
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="unchecked",
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "last_check_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_proxies_workspace_id", "proxies", ["workspace_id"])
    op.create_index("ix_proxies_status", "proxies", ["status"])


def downgrade() -> None:
    op.drop_index("ix_proxies_status", table_name="proxies")
    op.drop_index("ix_proxies_workspace_id", table_name="proxies")
    op.drop_table("proxies")
