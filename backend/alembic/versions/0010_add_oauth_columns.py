"""add oauth_provider columns to users

Phase 1 (task WW) — back the OAuth login flow described in
``docs/ARCHITECTURE`` §2.3 / Phase 1 closure. Adds two nullable columns
to ``users``:

* ``oauth_provider`` — short identifier of the IdP (``"google"`` or
  ``"github"`` today; intentionally a free-form ``TEXT`` so a future
  provider can be added without a schema migration).
* ``oauth_provider_user_id`` — the IdP's stable subject identifier for
  the user (Google ``sub`` claim, GitHub numeric ``id`` stringified).

The combination ``(oauth_provider, oauth_provider_user_id)`` must be
unique so the same external identity can never resolve to two local
users. A *partial* unique index (``WHERE oauth_provider IS NOT NULL``)
expresses this without preventing the existing password-only users from
sharing ``NULL`` on both columns — a plain ``UNIQUE`` constraint would
reject multiple NULL pairs only in some DBs and would create a confusing
constraint shape for password users.

Existing password users are untouched: both columns default to NULL and
the legacy ``password_hash`` / login path keep working. OAuth users get
``oauth_provider`` / ``oauth_provider_user_id`` set at signup-via-OAuth
and may also have ``password_hash`` populated to a random unusable hash
(the NOT NULL constraint on ``password_hash`` is preserved — see
:func:`backend.db_auth.signup_oauth`).

Revision ID: 0010_add_oauth_columns
Revises: 0009_add_rls
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_add_oauth_columns"
down_revision: Union[str, Sequence[str], None] = "0009_add_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("oauth_provider", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("oauth_provider_user_id", sa.Text(), nullable=True),
    )
    # Partial unique index: only enforce uniqueness for rows that actually
    # carry an OAuth identity. Password-only users keep both columns NULL
    # and are unaffected.
    op.execute(
        """
        CREATE UNIQUE INDEX ux_users_oauth
            ON users (oauth_provider, oauth_provider_user_id)
            WHERE oauth_provider IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_users_oauth")
    op.drop_column("users", "oauth_provider_user_id")
    op.drop_column("users", "oauth_provider")
