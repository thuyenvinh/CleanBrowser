"""add email_verification_tokens table

Phase 1 closure — wire up the on-disk half of the email verification flow
that lives behind ``POST /api/auth/signup``, ``GET /api/auth/verify-email``
and ``POST /api/auth/resend-verification`` (see ``backend/routers/auth.py``).

The user-facing token is generated server-side as a 256-bit URL-safe random
blob and emailed once. We only persist its SHA-256 hash so a database leak
cannot be replayed against the verify endpoint — the same pattern already
used for ``user_api_keys.key_hash``.

Each row carries its own expiry (24h by default) and a ``used_at`` marker
so consumption is one-shot. We index by ``user_id`` since the resend path
optionally garbage-collects prior outstanding tokens for the same user; the
``UNIQUE`` on ``token_hash`` doubles as the lookup index for verify.

Revision ID: 0011_add_email_verification_tokens
Revises: 0009_add_rls
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_add_email_verification_tokens"
down_revision: Union[str, Sequence[str], None] = "0009_add_rls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "expires_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "used_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_evt_user_id", "email_verification_tokens", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_evt_user_id", table_name="email_verification_tokens"
    )
    op.drop_table("email_verification_tokens")
