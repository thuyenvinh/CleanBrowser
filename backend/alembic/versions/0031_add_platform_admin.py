"""add users.is_platform_admin for cross-tenant super-admin role

Platform admins are NOT a workspace role — they sit above the tenant
boundary so a single operator account can moderate the marketplace, page
through every tenant's billing, disable abusive accounts, etc. Promotion
happens via ``scripts/seed_admin.py`` or another platform admin calling
``POST /api/admin/users/{id}/promote``; the first admin is bootstrapped
by the seed script because there is intentionally no UI to mint one
without an existing one.

Default ``FALSE`` for every existing row + ``NOT NULL`` so the dependency
``require_platform_admin`` can read the column without a defensive
fallback. The column lives on ``users`` (not a separate join table)
because each row already enforces a UNIQUE (tenant_id, email) — a single
user account either is or isn't a platform admin, no fan-out.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0031_platform_admin"
down_revision: Union[str, Sequence[str], None] = "0030_password_changed_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_platform_admin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Partial index — most users are not admins; an index on the few
    # ``true`` rows keeps the ``WHERE is_platform_admin`` lookup cheap
    # without bloating writes for the 99.99% common case.
    op.execute(
        "CREATE INDEX ix_users_platform_admin "
        "ON users (id) WHERE is_platform_admin = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_platform_admin")
    op.drop_column("users", "is_platform_admin")
