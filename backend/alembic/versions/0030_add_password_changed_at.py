"""add users.password_changed_at for JWT invalidation on reset

Security review M-07. Before this migration, /api/auth/reset-password
updated ``users.password_hash`` but every JWT issued before the rotation
stayed valid until its 24h ``exp`` — so a compromised session cookie
remained usable even after the legitimate user reset their password.

The fix is a per-user invalidation timestamp: ``get_optional_user``
compares the JWT's ``iat`` claim against ``users.password_changed_at`` and
rejects the cookie if the token was issued before the most recent reset.
``server_default=now()`` backfills existing rows so previously-issued
tokens stay valid through their TTL.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0030_password_changed_at"
down_revision: Union[str, Sequence[str], None] = "0029_unique_name_per_workspace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "password_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
