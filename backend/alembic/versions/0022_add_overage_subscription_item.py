"""add overage_subscription_item_id + reported tracking on overage_events

Phase 7 phase 2 — turns the local-only overage ledger from migration
``0020_add_overage`` into a Stripe-relay queue. Two pieces:

1. ``subscriptions.overage_subscription_item_id`` (TEXT, nullable) —
   the Stripe ``subscription_item`` id for the metered overage price on
   that subscription. Distinct from ``provider_subscription_id`` because
   Stripe usage records are posted against a *line item*, not the
   subscription itself: a single subscription can carry a flat base price
   plus a metered overage price, each with their own item id.

   Nullable because (a) the ``free`` plan has no overage price and (b)
   self-host installs without Stripe leave this empty — the worker
   short-circuits when no item id is set rather than erroring.

2. Three new columns on ``overage_events`` to track the relay state:

   * ``reported`` (BOOLEAN NOT NULL DEFAULT false) — flips to true once
     Stripe has accepted the usage record. The flusher worker only
     selects rows with ``reported = false`` so finished rows drop out of
     the scan immediately.
   * ``reported_at`` (TIMESTAMPTZ, nullable) — wall-clock time of the
     successful Stripe call. Useful for "how stale is our Stripe sync?"
     dashboards without having to join through Stripe's API.
   * ``stripe_usage_record_id`` already exists on the table from
     migration 0020 — we don't re-add it, the flusher just populates it
     when ``mark_reported`` runs.

3. A new partial index ``ix_overage_events_unreported`` over
   ``(reported, occurred_at) WHERE reported = false`` — the flusher's
   working set. The old partial index from 0020 (``WHERE
   stripe_usage_record_id IS NULL``) is dropped because the new
   ``reported`` flag is the authoritative "needs sending" signal; the
   two would diverge if someone manually wrote a ``stripe_usage_record_id``
   without flipping ``reported``.

Revision ID: 0022_add_overage_subscription_item
Revises: 0021_add_profile_version_files
Create Date: 2026-05-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_add_overage_subscription_item"
down_revision: Union[str, Sequence[str], None] = "0021_add_profile_version_files"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── subscriptions: overage line-item id ─────────────────────────────────
    op.add_column(
        "subscriptions",
        sa.Column(
            "overage_subscription_item_id",
            sa.Text(),
            nullable=True,
        ),
    )

    # ── overage_events: reported tracking ───────────────────────────────────
    op.add_column(
        "overage_events",
        sa.Column(
            "reported",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "overage_events",
        sa.Column(
            "reported_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )

    # Replace the old "WHERE stripe_usage_record_id IS NULL" index from
    # migration 0020 with one keyed off the authoritative ``reported``
    # flag. Same name; the flusher worker queries by ``reported = false``.
    op.execute("DROP INDEX IF EXISTS ix_overage_events_unreported")
    op.execute(
        "CREATE INDEX ix_overage_events_unreported "
        "ON overage_events (reported, occurred_at) "
        "WHERE reported = false"
    )


def downgrade() -> None:
    # Restore the original predicate from migration 0020 so a partial
    # downgrade leaves the schema as that migration left it.
    op.execute("DROP INDEX IF EXISTS ix_overage_events_unreported")
    op.execute(
        "CREATE INDEX ix_overage_events_unreported "
        "ON overage_events (stripe_usage_record_id) "
        "WHERE stripe_usage_record_id IS NULL"
    )

    op.drop_column("overage_events", "reported_at")
    op.drop_column("overage_events", "reported")
    op.drop_column("subscriptions", "overage_subscription_item_id")
