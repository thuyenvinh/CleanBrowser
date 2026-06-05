"""add tenants, users, workspaces, workspace_members, user_api_keys

Phase 1 multi-tenant auth/RBAC scaffolding. Creates the bare schema that the
upcoming JWT auth, RBAC dependency, and audit log will reference. See
``docs/ARCHITECTURE`` §2.2 (domain model) and §2.3 (auth + RBAC matrix).

This migration intentionally does NOT add ``workspace_id`` /
``started_by_user_id`` columns to ``profiles`` or ``profile_sessions`` — that
will land in a separate follow-up migration once the API layer is wired (Wave
2), to keep the blast radius of each migration small.

Revision ID: 0003_add_auth_tables
Revises: 0002_add_profile_sessions
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_add_auth_tables"
down_revision: Union[str, Sequence[str], None] = "0002_add_profile_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ tenants
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "plan_id", sa.Text(), nullable=False, server_default="free",
        ),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="active",
        ),
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

    # -------------------------------------------------------------------- users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("mfa_secret", sa.Text(), nullable=True),
        sa.Column(
            "email_verified_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "status", sa.Text(), nullable=False, server_default="active",
        ),
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
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    # Global email uniqueness (case-insensitive) on top of the per-tenant one;
    # belt-and-braces so a single human can only ever own one account.
    op.execute(
        "CREATE UNIQUE INDEX ux_users_email_global ON users (lower(email))"
    )

    # --------------------------------------------------------------- workspaces
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_workspaces_tenant_id", "workspaces", ["tenant_id"])

    # -------------------------------------------------------- workspace_members
    op.create_table(
        "workspace_members",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "user_id", name="pk_workspace_members"
        ),
    )
    op.create_index(
        "ix_workspace_members_user_id", "workspace_members", ["user_id"]
    )

    # ------------------------------------------------------------ user_api_keys
    op.create_table(
        "user_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['*']::TEXT[]"),
        ),
        sa.Column(
            "last_used_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "revoked_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.create_index("ix_user_api_keys_user_id", "user_api_keys", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_api_keys_user_id", table_name="user_api_keys")
    op.drop_table("user_api_keys")

    op.drop_index(
        "ix_workspace_members_user_id", table_name="workspace_members"
    )
    op.drop_table("workspace_members")

    op.drop_index("ix_workspaces_tenant_id", table_name="workspaces")
    op.drop_table("workspaces")

    op.execute("DROP INDEX IF EXISTS ux_users_email_global")
    op.drop_table("users")

    op.drop_table("tenants")
