"""add marketplace moderation columns + creator submission support

Phase 6 phase 2 — opens the marketplace catalog to user-submitted apps via
a creator portal. Until now the only path to a public listing was the
seed migration (`0018_add_marketplace.py`); this migration adds the
moderation workflow that turns the catalog into a real submission queue.

Schema additions on `marketplace_apps`:

* ``moderation_status`` — text enum-ish (``'approved' | 'pending' |
  'rejected'``). Defaults to ``'approved'`` so the three seeded official
  apps keep their public visibility on upgrade without backfill.
* ``submitted_by_user_id`` — author UUID for the audit trail. Not FK'd
  (matches the ledger style of ``installed_by_user_id`` so deleting a
  user doesn't cascade-purge their contributions).
* ``submitted_at`` — submission timestamp; powers the pending-queue
  ordering.
* ``moderation_notes`` — free-form admin notes attached on
  approve/reject.

Index reshape:

* Drop the old partial index ``ix_marketplace_apps_category`` (scoped
  to ``is_public = true``) and recreate it scoped to
  ``is_public = true AND moderation_status = 'approved'`` so public
  browse queries only ever scan listing-ready rows.
* Add ``ix_marketplace_apps_moderation`` — a tiny partial index over
  the pending/rejected rows that powers the admin queue without
  dragging the approved set into the index.

Downgrade reverses everything: drop new index, restore the original
category index, drop the four new columns.

Revision ID: 0019_add_marketplace_moderation
Revises: 0018_add_marketplace
Create Date: 2026-05-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_add_marketplace_moderation"
down_revision: Union[str, Sequence[str], None] = "0018_add_marketplace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── New columns ─────────────────────────────────────────────────────────
    op.add_column(
        "marketplace_apps",
        sa.Column(
            "moderation_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'approved'"),
        ),
    )
    op.add_column(
        "marketplace_apps",
        sa.Column(
            "submitted_by_user_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.add_column(
        "marketplace_apps",
        sa.Column(
            "submitted_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "marketplace_apps",
        sa.Column("moderation_notes", sa.Text(), nullable=True),
    )

    # Belt-and-braces: any row that somehow has NULL after the default kicks
    # in (e.g. a manual INSERT pre-migration) is forced to 'approved' so the
    # public listing query never silently hides seeded content.
    op.execute(
        "UPDATE marketplace_apps "
        "SET moderation_status = 'approved' "
        "WHERE moderation_status IS NULL"
    )

    # ── Index reshape ──────────────────────────────────────────────────────
    # Old category index scoped to public-only; the new browse query also
    # filters on moderation_status='approved' so the index must follow.
    op.drop_index(
        "ix_marketplace_apps_category", table_name="marketplace_apps"
    )
    op.create_index(
        "ix_marketplace_apps_category",
        "marketplace_apps",
        ["category"],
        postgresql_where=sa.text(
            "is_public = true AND moderation_status = 'approved'"
        ),
    )

    # Tiny partial index for the admin queue: only ever scans pending or
    # rejected rows, ordered by submission time (newest first).
    op.create_index(
        "ix_marketplace_apps_moderation",
        "marketplace_apps",
        ["moderation_status", sa.text("submitted_at DESC")],
        postgresql_where=sa.text(
            "moderation_status IN ('pending', 'rejected')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_apps_moderation", table_name="marketplace_apps"
    )
    op.drop_index(
        "ix_marketplace_apps_category", table_name="marketplace_apps"
    )
    # Restore the original (0018) partial index.
    op.create_index(
        "ix_marketplace_apps_category",
        "marketplace_apps",
        ["category"],
        postgresql_where=sa.text("is_public = true"),
    )

    op.drop_column("marketplace_apps", "moderation_notes")
    op.drop_column("marketplace_apps", "submitted_at")
    op.drop_column("marketplace_apps", "submitted_by_user_id")
    op.drop_column("marketplace_apps", "moderation_status")
