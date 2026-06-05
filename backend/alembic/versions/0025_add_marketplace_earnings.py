"""add marketplace revenue share + earnings ledger

Phase 6 phase 3 — turns the marketplace into a real two-sided revenue
surface. Until now the catalog only carried metadata + install ledger
(0018) plus moderation (0019); this migration introduces paid apps and
the per-install earnings rows that the creator dashboard later renders.

Schema additions on ``marketplace_apps``:

* ``price_cents`` — 0 means free (back-compat with every existing seed +
  user submission), > 0 means a one-time-per-workspace charge collected
  at install time. The router records earnings rows for paid installs
  even when payment collection itself is deferred (see Phase 8 TODO in
  the install endpoint) so the ledger stays the source of truth.
* ``creator_user_id`` — uuid of the human who owns the revenue split.
  Not FK'd (matches ``submitted_by_user_id`` / ``installed_by_user_id``
  audit-ledger style: deleting a user must not cascade-purge their
  earnings history). Backfilled from ``submitted_by_user_id`` so every
  pre-existing user-submitted app gets credited automatically.
* ``revenue_share_pct`` — percentage paid out to the creator (default
  70). Platform keeps ``100 - revenue_share_pct``. Per-row so future
  promo deals (90/10 for a featured creator) don't require schema
  changes.

New table ``marketplace_earnings``:

* One row per paid install — never deleted (the ``install_id`` FK is
  ``ON DELETE SET NULL`` so a creator uninstalling later doesn't wipe
  the earning, mirroring the same audit-ledger pattern).
* ``gross_cents`` snapshots what the buyer paid; ``creator_cents`` +
  ``platform_cents`` snapshot the split at event time so re-pricing the
  app or changing ``revenue_share_pct`` later cannot retroactively
  rewrite history.
* ``status`` walks ``pending → available → paid_out``. The
  ``available_at`` timestamp is set to ``created_at + 14 days`` so the
  earning sits in escrow during the refund window before the creator
  can request payout. ``refunded`` is a terminal state for when the
  buyer's purchase is reversed.
* Two indexes:
  - ``ix_marketplace_earnings_creator`` powers the dashboard query
    (``WHERE creator_user_id = ? ORDER BY created_at DESC``).
  - ``ix_marketplace_earnings_available`` is a partial index over only
    ``status='available'`` rows so the daily payout worker that flips
    pending → available stays index-only.

Revision ID: 0025_add_marketplace_earnings
Revises: 0023_add_service_checks
Create Date: 2026-05-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_add_marketplace_earnings"
down_revision: Union[str, Sequence[str], None] = "0023_add_service_checks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── marketplace_apps: price + creator + revenue share columns ────────────
    op.add_column(
        "marketplace_apps",
        sa.Column(
            "price_cents",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "marketplace_apps",
        sa.Column(
            "creator_user_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.add_column(
        "marketplace_apps",
        sa.Column(
            "revenue_share_pct",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("70"),
        ),
    )

    # Backfill: every existing user submission already has the author in
    # ``submitted_by_user_id``; carry that across so their installs start
    # earning the day this migration lands. Seeded official apps have no
    # submitter and stay NULL (the platform keeps 100% of their revenue).
    op.execute(
        "UPDATE marketplace_apps "
        "SET creator_user_id = submitted_by_user_id "
        "WHERE submitted_by_user_id IS NOT NULL"
    )

    # ── marketplace_earnings: per-install ledger ─────────────────────────────
    op.create_table(
        "marketplace_earnings",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "app_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("marketplace_apps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # SET NULL so an uninstall doesn't wipe the earning record — the
        # creator still earned the money even if the buyer later removed
        # the app from their workspace.
        sa.Column(
            "install_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenant_app_installs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Not FK'd: audit-ledger style (matches creator_user_id on apps).
        sa.Column(
            "creator_user_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
        ),
        sa.Column(
            "buyer_tenant_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
        ),
        sa.Column("gross_cents", sa.Integer(), nullable=False),
        sa.Column("creator_cents", sa.Integer(), nullable=False),
        sa.Column("platform_cents", sa.Integer(), nullable=False),
        sa.Column(
            "currency", sa.Text(), nullable=False, server_default=sa.text("'usd'")
        ),
        # 'pending' → 'available' → 'paid_out'; 'refunded' is terminal.
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "available_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "paid_out_at",
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
        "ix_marketplace_earnings_creator",
        "marketplace_earnings",
        ["creator_user_id", sa.text("created_at DESC")],
    )
    # Partial index — the payout worker only ever scans available rows,
    # ordering by ``available_at`` to pick the oldest eligible earning.
    op.create_index(
        "ix_marketplace_earnings_available",
        "marketplace_earnings",
        ["status", "available_at"],
        postgresql_where=sa.text("status = 'available'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketplace_earnings_available", table_name="marketplace_earnings"
    )
    op.drop_index(
        "ix_marketplace_earnings_creator", table_name="marketplace_earnings"
    )
    op.drop_table("marketplace_earnings")

    op.drop_column("marketplace_apps", "revenue_share_pct")
    op.drop_column("marketplace_apps", "creator_user_id")
    op.drop_column("marketplace_apps", "price_cents")
