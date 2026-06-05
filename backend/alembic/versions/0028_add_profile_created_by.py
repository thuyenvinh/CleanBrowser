"""add created_by_user_id to profiles (C7 RBAC fix)

Critical bug C7 — any editor in a workspace could delete profiles created
by other members of the same workspace. The router-layer fix
(``backend/routers/profiles.py::_check_mutation_permission``) needs to know
who originally created a profile so it can short-circuit "creator can always
delete their own profile" and reject editors trying to delete someone
else's. This migration introduces the column that backs that check.

The column is intentionally NULLABLE — pre-existing rows have no recorded
creator, and the helper treats a NULL ``created_by_user_id`` as "no owner
on file" so the role check (admin+ required) still applies. Test-suite and
legacy AUTH_TOKEN flows that create profiles without a session likewise
leave the column NULL, matching the same pattern as ``workspace_id`` from
migration 0005.

No FK constraint is added: an audit-ledger style of bookkeeping (mirrors
the ``triggered_by_user_id`` / ``created_by_user_id`` columns elsewhere in
the schema). Deleting a user should not strip the creator trail of every
profile they ever made.

Revision ID: 0028_add_profile_created_by
Revises: 0027_add_password_reset_tokens
Create Date: 2026-06-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_add_profile_created_by"
down_revision: Union[str, Sequence[str], None] = "0027_add_password_reset_tokens"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_profiles_created_by",
        "profiles",
        ["created_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_profiles_created_by", table_name="profiles")
    op.drop_column("profiles", "created_by_user_id")
