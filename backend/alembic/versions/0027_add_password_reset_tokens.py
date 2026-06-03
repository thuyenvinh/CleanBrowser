"""add password_reset_tokens table

Phase 7 closure — bug C6 (forgot-password flow was missing entirely, so a
user who lost their password had no recovery path short of contacting an
operator with database access).

The on-disk shape mirrors ``email_verification_tokens`` from migration
0011: a single URL-safe random blob is emailed once and only its SHA-256
lives in ``token_hash`` so a DB leak cannot be replayed against
``POST /api/auth/reset-password``. We index by ``user_id`` so the reset
endpoint can (optionally, in a later wave) garbage-collect prior
outstanding tokens for the same user the way the verification flow does.

TTL is intentionally shorter than email verification (1h vs 24h) because
a password reset gives the holder unilateral control of the account —
a wider window magnifies the blast radius of a leaked link (email
forwarding, archive scrapers, shoulder-surfing).

Revision ID: 0027_add_password_reset_tokens
Revises: 0026_add_pending_installs
Create Date: 2026-06-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_add_password_reset_tokens"
down_revision: Union[str, Sequence[str], None] = "0026_add_pending_installs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
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
    op.create_index("ix_prt_user_id", "password_reset_tokens", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_prt_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
