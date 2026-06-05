"""initial schema: profiles + profile_tags

Mirrors the legacy SQLite schema. UUIDs are generated at the application layer
(``uuid.uuid4()`` in ``database.create_profile``) so the migration does not
depend on the ``uuid-ossp`` extension. ``launch_args`` is stored as native
JSONB instead of a TEXT JSON blob.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("fingerprint_seed", sa.Integer(), nullable=False),
        sa.Column("proxy", sa.Text(), nullable=True),
        sa.Column("timezone", sa.Text(), nullable=True),
        sa.Column("locale", sa.Text(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=True, server_default="windows"),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("screen_width", sa.Integer(), nullable=True, server_default="1920"),
        sa.Column("screen_height", sa.Integer(), nullable=True, server_default="1080"),
        sa.Column("gpu_vendor", sa.Text(), nullable=True),
        sa.Column("gpu_renderer", sa.Text(), nullable=True),
        sa.Column("hardware_concurrency", sa.Integer(), nullable=True),
        sa.Column("humanize", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("human_preset", sa.Text(), nullable=True, server_default="default"),
        sa.Column("headless", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("geoip", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("clipboard_sync", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("auto_launch", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("color_scheme", sa.Text(), nullable=True),
        sa.Column(
            "launch_args",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("user_data_dir", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_profiles_created_at", "profiles", ["created_at"])

    op.create_table(
        "profile_tags",
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("profile_id", "tag", name="pk_profile_tags"),
    )
    op.create_index("ix_profile_tags_profile_id", "profile_tags", ["profile_id"])


def downgrade() -> None:
    op.drop_index("ix_profile_tags_profile_id", table_name="profile_tags")
    op.drop_table("profile_tags")
    op.drop_index("ix_profiles_created_at", table_name="profiles")
    op.drop_table("profiles")
