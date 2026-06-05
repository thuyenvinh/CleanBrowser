"""add workspace_id to profiles

Phase 1 multi-tenant wiring. Adds a NULLABLE ``workspace_id`` column to
``profiles`` so each profile can belong to a workspace. The column is
NULLABLE on purpose:

* Profiles created before this migration ran (legacy / single-tenant
  installs) have no workspace and stay reachable in legacy AUTH_TOKEN mode.
* Profiles created via the API without an authenticated user (test suite,
  scripts hitting the API directly) also keep ``workspace_id = NULL``.

The route layer (``routers/profiles.py``) is responsible for scoping reads
to ``workspace_id IN (user's workspaces)`` when a session user is present.

Revision ID: 0005_add_workspace_id_to_profiles
Revises: 0004_add_audit_logs
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_profile_workspace_id"
down_revision: Union[str, Sequence[str], None] = "0004_add_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_profiles_workspace_id",
        "profiles",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_profiles_workspace_id", "profiles", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_profiles_workspace_id", table_name="profiles")
    op.drop_constraint(
        "fk_profiles_workspace_id", "profiles", type_="foreignkey"
    )
    op.drop_column("profiles", "workspace_id")
