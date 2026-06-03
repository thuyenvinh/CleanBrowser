"""add marketplace_pending_installs (defer paid-app install until Stripe)

Phase 6 phase 4 — closes bug C2 (paid marketplace installs recorded
creator earnings without ever charging the buyer). The install endpoint
now redirects paid installs through Stripe Checkout, and this table
remembers the in-flight install so the post-payment callback can pick
up where the request left off (workspace + buyer + app context).

Schema notes:

* ``stripe_session_id`` — Stripe's ``cs_…`` id, ``UNIQUE`` so the
  callback can do a single indexed lookup and a duplicate redirect from
  Stripe can't double-install.
* ``status`` — ``'pending'`` (default) → ``'completed'`` once the
  callback verifies the payment and runs the real install + earning,
  or ``'cancelled'`` if we ever build an explicit cancel surface. We
  keep completed rows for audit (mirrors the rest of the marketplace
  ledger pattern).
* Both FKs cascade-delete: if the workspace or app vanishes before the
  buyer completes payment, the pending row is meaningless and there's
  no creator earning row pointing at it yet.

Revision ID: 0026_add_pending_installs
Revises: 0024_add_automation_webhooks
Create Date: 2026-06-03
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_add_pending_installs"
down_revision: Union[str, Sequence[str], None] = "0024_add_automation_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "marketplace_pending_installs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "app_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("marketplace_apps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Not FK'd: audit-ledger style — a buyer deletion shouldn't wipe
        # the trail of in-flight purchases they kicked off.
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=False),
            nullable=False,
        ),
        sa.Column("stripe_session_id", sa.Text(), nullable=True, unique=True),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Hot-path lookup from the Stripe redirect callback.
    op.create_index(
        "ix_pending_installs_session",
        "marketplace_pending_installs",
        ["stripe_session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pending_installs_session",
        table_name="marketplace_pending_installs",
    )
    op.drop_table("marketplace_pending_installs")
