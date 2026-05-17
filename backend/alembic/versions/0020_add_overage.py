"""add overage billing support: plans flags + overage_events table

Phase 7 phase 1 — turns the hard 402 cap on ``automation_minutes`` into a
soft cap with metered overage billing. Two pieces:

1. Three new columns on ``plans`` describing whether the plan tolerates
   going over the cap and at what unit price:

   * ``allow_overage`` (BOOLEAN, default false) — gates the whole feature.
     Defaulting to ``false`` preserves the existing hard-cap behaviour on
     upgrade for any plan we don't explicitly opt in.
   * ``overage_price_per_minute_cents`` (INTEGER, nullable) — the unit
     price we'll charge per extra automation minute. Nullable because the
     phase-1 ``free`` plan keeps the hard cap (no overage), and self-host
     installs may also leave it NULL.
   * ``stripe_overage_price_id`` (TEXT, nullable) — optional Stripe
     metered-price ID. When set, a future reconciliation job (phase 2)
     can relay overage events to Stripe Usage Records under this price.

2. A new ``overage_events`` table — one row per "we let the tenant go
   over the cap" decision. The local ledger is intentionally
   authoritative: even if Stripe is unreachable when an overage happens,
   the event lands in Postgres and a later reconciler can replay it
   (``stripe_usage_record_id IS NULL`` is the unreported queue).

   Schema choices:

   * ``resource`` is TEXT (not enum) so adding ``concurrent_runs`` /
     ``storage_gb`` overage in phase 2 doesn't require a migration.
   * ``unit_price_cents`` is a snapshot of the plan price at event time —
     re-pricing the plan later must not retroactively change historical
     bills.
   * ``period_start`` / ``period_end`` are DATE (calendar month) to match
     ``usage_counters.period_start`` for trivial joins on the billing
     period.
   * ``subscription_id`` uses ``ON DELETE SET NULL`` (not CASCADE): if a
     tenant churns and we drop their subscription, we still want the
     overage events on file for any final invoicing.

3. Seed — flip ``allow_overage = true`` and set ``5¢/minute`` on the
   three paid tiers (``starter``, ``pro``, ``team``). ``free`` stays
   hard-capped on purpose (free plans should never silently bill users).

Revision ID: 0020_add_overage
Revises: 0019_add_marketplace_moderation
Create Date: 2026-05-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_add_overage"
down_revision: Union[str, Sequence[str], None] = "0019_add_marketplace_moderation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── plans: overage flags ────────────────────────────────────────────────
    op.add_column(
        "plans",
        sa.Column(
            "allow_overage",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "plans",
        sa.Column(
            "overage_price_per_minute_cents",
            sa.Integer(),
            nullable=True,
        ),
    )
    op.add_column(
        "plans",
        sa.Column("stripe_overage_price_id", sa.Text(), nullable=True),
    )

    # ── overage_events ──────────────────────────────────────────────────────
    op.create_table(
        "overage_events",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # 'automation_minutes' today; 'concurrent_runs' / 'storage_gb' later.
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        # Snapshot of plan.overage_price_per_minute_cents at event time so
        # historical bills don't drift when plans get re-priced.
        sa.Column("unit_price_cents", sa.Integer(), nullable=True),
        # NULL until the daily reconcile job (phase 2) pushes it to Stripe.
        sa.Column("stripe_usage_record_id", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
    )
    op.create_index(
        "ix_overage_events_tenant_period",
        "overage_events",
        ["tenant_id", "period_start"],
    )
    # Partial index over the "not yet reported to Stripe" queue. Reconcile
    # job scans this without dragging the reported-and-done rows.
    op.execute(
        "CREATE INDEX ix_overage_events_unreported "
        "ON overage_events (stripe_usage_record_id) "
        "WHERE stripe_usage_record_id IS NULL"
    )

    # ── seed: enable overage on paid tiers at 5¢/minute ────────────────────
    op.execute(
        "UPDATE plans SET allow_overage = true, "
        "overage_price_per_minute_cents = 5 "
        "WHERE id IN ('starter', 'pro', 'team')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_overage_events_unreported")
    op.drop_index(
        "ix_overage_events_tenant_period", table_name="overage_events"
    )
    op.drop_table("overage_events")

    op.drop_column("plans", "stripe_overage_price_id")
    op.drop_column("plans", "overage_price_per_minute_cents")
    op.drop_column("plans", "allow_overage")
