"""add proxy_id to profiles

Phase 2 (task U) — link a profile to a row in the workspace-level proxy
pool added by migration ``0006_add_proxies``. The legacy ``profiles.proxy``
TEXT column is intentionally kept so existing rows (and the legacy single-
tenant ``host:port:user:pass`` field) keep working; the launch flow now
prefers ``proxy_id`` when set and falls back to ``proxy`` otherwise.

The FK uses ``ON DELETE SET NULL`` so deleting a proxy from the pool does
not cascade-destroy profiles — it just orphans the link, and the launch
flow degrades to "no proxy" (since the legacy ``proxy`` field is not
touched by the FK).

Revision ID: 0007_profile_proxy_id
Revises: 0006_add_proxies
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_profile_proxy_id"
down_revision: Union[str, Sequence[str], None] = "0006_add_proxies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column(
            "proxy_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_profiles_proxy_id",
        "profiles",
        "proxies",
        ["proxy_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_profiles_proxy_id", "profiles", ["proxy_id"])


def downgrade() -> None:
    op.drop_index("ix_profiles_proxy_id", table_name="profiles")
    op.drop_constraint(
        "fk_profiles_proxy_id", "profiles", type_="foreignkey"
    )
    op.drop_column("profiles", "proxy_id")
