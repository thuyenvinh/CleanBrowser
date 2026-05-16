"""add profile_sessions table

Persists browser session lifecycle state outside the in-memory
``BrowserManager.running`` dict so that future worker tiers (Phase 3) can split
launch responsibility across multiple processes/pods. See ``docs/ARCHITECTURE``
§2.2.

The ``started_by_user_id`` column described in the architecture doc is
intentionally omitted here — it will be added together with the ``users`` table
in Phase 1 via a follow-up migration.

Revision ID: 0002_add_profile_sessions
Revises: 0001_initial
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_add_profile_sessions"
down_revision: Union[str, Sequence[str], None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profile_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            sa.Text(),
            nullable=False,
            server_default="local",
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("display_num", sa.Integer(), nullable=True),
        sa.Column("ws_port", sa.Integer(), nullable=True),
        sa.Column("cdp_port", sa.Integer(), nullable=True),
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "ended_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_profile_sessions_profile_id_active",
        "profile_sessions",
        ["profile_id"],
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_index(
        "ix_profile_sessions_status",
        "profile_sessions",
        ["status"],
    )
    # Enforce at most one active session per profile.
    op.create_index(
        "ux_profile_sessions_one_active",
        "profile_sessions",
        ["profile_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_profile_sessions_one_active", table_name="profile_sessions")
    op.drop_index("ix_profile_sessions_status", table_name="profile_sessions")
    op.drop_index(
        "ix_profile_sessions_profile_id_active", table_name="profile_sessions"
    )
    op.drop_table("profile_sessions")
