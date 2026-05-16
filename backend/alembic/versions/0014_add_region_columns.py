"""add region columns to workspaces and profiles

Phase 3 wave 2 (task GGG) — backs the region selector described in
``docs/ARCHITECTURE`` §2.4. Adds:

* ``workspaces.default_region`` — non-null, defaults to ``'local'`` so every
  existing row gets a sensible value at migration time.
* ``profiles.region`` — nullable; ``NULL`` means "inherit from workspace".

The matching code path that resolves the effective region for a profile
lives in :func:`backend.regions.resolve_for_profile`: profile.region wins,
falling back to the workspace default, then to the configured global default.

Phase 3 phase 2 ships only the schema + the region registry + a single
``GET /api/regions`` endpoint. The browser_manager / Worker pool wiring
(scheduling launches to a worker in the requested region) lands in a later
wave; for now a region mismatch falls back to ``'local'`` with a warning.

Revision ID: 0014_add_region_columns
Revises: 0013_add_profile_versions
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014_add_region_columns"
down_revision: Union[str, Sequence[str], None] = "0013_add_profile_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "default_region",
            sa.Text(),
            nullable=False,
            server_default="local",
        ),
    )
    op.add_column(
        "profiles",
        sa.Column("region", sa.Text(), nullable=True),
    )
    # Partial index: only profiles that explicitly override the workspace
    # default are queried by region. Saves space on the (very common) NULL
    # rows that inherit.
    op.execute(
        "CREATE INDEX ix_profiles_region "
        "ON profiles (region) WHERE region IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_profiles_region")
    op.drop_column("profiles", "region")
    op.drop_column("workspaces", "default_region")
