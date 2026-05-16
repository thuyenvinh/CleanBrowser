"""add billing tables: plans, subscriptions, usage_counters

Phase 5 wave 1 (task HHH) — backs the billing & metering story described
in ``docs/ARCHITECTURE`` §2.8. Introduces three new tables:

* ``plans`` — catalogue of subscription tiers (free, starter, pro, team).
  The PK is a stable string slug (e.g. ``'pro'``) because every billing
  surface (UI, Stripe metadata, audit logs) references plans by that
  slug; a UUID here would just make joins less readable. Per-plan limit
  columns use ``NULL`` to mean "unlimited" so enforcement code can short
  circuit on ``IS NULL`` without picking a sentinel.

* ``subscriptions`` — one row per tenant subscription. ``tenant_id``
  cascades on delete (tearing down a tenant tears down its subs). The
  ``plan_id`` FK uses ``RESTRICT`` so an operator cannot accidentally
  drop a plan that still has live subscribers; a guarded migration is
  needed instead. A partial UNIQUE index enforces "at most one
  active-ish subscription per tenant" without blocking the historical
  rows left behind by ``cancelled`` / ``expired`` records.

* ``usage_counters`` — one row per (tenant, billing month). The period
  uses ``DATE`` (first/last day of the calendar month UTC) because all
  rollups are month-grained; storing TIMESTAMPTZ here would just invite
  off-by-one bugs around month boundaries. ``UNIQUE (tenant_id,
  period_start)`` is what :func:`backend.db_billing.get_or_create_current_period`
  upserts on.

The seed inserts four default plans so a fresh install can attach the
``free`` plan to brand-new tenants without any operator action.

This migration is schema-only — no router, dependency or quota code is
wired here. That landing comes in subsequent Phase 5 waves (Stripe /
VNPay webhooks in agent III, quota enforcement in agent JJJ).

Revision ID: 0015_add_billing
Revises: 0014_add_region_columns
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_add_billing"
down_revision: Union[str, Sequence[str], None] = "0014_add_region_columns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ----------------------------------------------------------------- plans
    op.create_table(
        "plans",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "price_cents",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "interval",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'month'"),
        ),
        sa.Column("stripe_price_id", sa.Text(), nullable=True),
        sa.Column("vnpay_product_id", sa.Text(), nullable=True),
        # NULL == unlimited on every limit column.
        sa.Column("max_profiles", sa.Integer(), nullable=True),
        sa.Column("max_concurrent_runs", sa.Integer(), nullable=True),
        sa.Column("max_workspace_members", sa.Integer(), nullable=True),
        sa.Column("max_automation_minutes", sa.Integer(), nullable=True),
        sa.Column("max_storage_gb", sa.Integer(), nullable=True),
        sa.Column(
            "allow_regions",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['local']::TEXT[]"),
        ),
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # --------------------------------------------------------- subscriptions
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            sa.Text(),
            sa.ForeignKey("plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payment_provider", sa.Text(), nullable=True),
        sa.Column("provider_subscription_id", sa.Text(), nullable=True),
        sa.Column("provider_customer_id", sa.Text(), nullable=True),
        sa.Column(
            "current_period_start",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "current_period_end",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "trial_end",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"]
    )
    # Partial unique: at most one "live-ish" subscription per tenant.
    # Cancelled / expired rows accumulate as history without blocking.
    op.execute(
        "CREATE UNIQUE INDEX ux_subscriptions_active "
        "ON subscriptions (tenant_id) "
        "WHERE status IN ('active','trialing','past_due')"
    )

    # ------------------------------------------------------- usage_counters
    op.create_table(
        "usage_counters",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "profile_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "concurrent_runs_peak",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "automation_minutes_used",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "storage_gb_used",
            sa.Numeric(10, 3),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "workspace_members_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "period_start", name="uq_usage_counters_tenant_period"
        ),
    )
    op.create_index(
        "ix_usage_counters_tenant_period",
        "usage_counters",
        ["tenant_id", sa.text("period_start DESC")],
    )

    # ---------------------------------------------------------------- seed
    # Four default tiers. ``allow_regions`` widens with each tier; ``free``
    # is restricted to the always-available ``local`` worker. These rows
    # are referenced by ``get_tenant_limits()`` fallback in
    # :mod:`backend.db_billing` when a tenant has no active subscription.
    op.execute(
        """
        INSERT INTO plans (
            id, name, description, price_cents, interval,
            max_profiles, max_concurrent_runs, max_workspace_members,
            max_automation_minutes, max_storage_gb,
            allow_regions, sort_order
        ) VALUES
            ('free',    'Free',    'Hobby tier',           0,
             'month',  10,   2,    1,    60,    1,
             ARRAY['local']::TEXT[], 0),
            ('starter', 'Starter', 'Solo professional',    1900,
             'month',  100,  10,   3,    600,   10,
             ARRAY['local','us','eu']::TEXT[], 1),
            ('pro',     'Pro',     'Growing team',         4900,
             'month',  500,  50,   10,   3000,  50,
             ARRAY['local','us','eu','sg','jp']::TEXT[], 2),
            ('team',    'Team',    'Agency',               9900,
             'month',  2000, 200,  50,   12000, 200,
             ARRAY['local','us','eu','sg','jp','au','vn']::TEXT[], 3)
        """
    )


def downgrade() -> None:
    # Tables drop in reverse FK order. The seed rows in ``plans`` go away
    # with the table — no separate DELETE needed.
    op.drop_index(
        "ix_usage_counters_tenant_period", table_name="usage_counters"
    )
    op.drop_table("usage_counters")

    op.execute("DROP INDEX IF EXISTS ux_subscriptions_active")
    op.drop_index("ix_subscriptions_tenant_id", table_name="subscriptions")
    op.drop_table("subscriptions")

    op.drop_table("plans")
