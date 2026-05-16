"""add invoices table for billing history

Phase 5 closure (task NNN) — persists invoice events from payment
providers (Stripe ``invoice.payment_succeeded`` / ``invoice.payment_failed``
/ ``invoice.created`` webhooks, plus any VNPay confirmations relayed by
the operator). Lets a tenant see their billing history without leaving
the app.

Schema choices:

* ``tenant_id`` cascades on delete so wiping a tenant wipes its
  invoices. ``subscription_id`` only ``SET NULL`` because invoice
  history must survive subscription replacements/cancellations.

* ``(provider, provider_invoice_id)`` is the natural idempotency key:
  Stripe may redeliver the same webhook, and our ``create_invoice``
  helper handles that via ``ON CONFLICT … DO UPDATE``.

* ``amount_cents`` keeps the integer-cents convention from ``plans`` so
  cross-table maths stays in one currency unit. ``currency`` defaults
  to ``'usd'`` because the existing Stripe flow charges USD; VNPay rows
  store ``'vnd'``.

Revision ID: 0016_add_invoices
Revises: 0015_add_billing
Create Date: 2026-05-16
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0016_add_invoices"
down_revision: Union[str, Sequence[str], None] = "0015_add_billing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            sa.dialects.postgresql.UUID(as_uuid=False),
            sa.ForeignKey("subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_invoice_id", sa.Text(), nullable=False),
        sa.Column("number", sa.Text(), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False, server_default="usd"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("hosted_invoice_url", sa.Text(), nullable=True),
        sa.Column("invoice_pdf_url", sa.Text(), nullable=True),
        sa.Column("period_start", sa.dialects.postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("period_end", sa.dialects.postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("paid_at", sa.dialects.postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.dialects.postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("provider", "provider_invoice_id", name="uq_invoices_provider_id"),
    )
    op.create_index(
        "ix_invoices_tenant_created",
        "invoices",
        ["tenant_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_tenant_created", table_name="invoices")
    op.drop_table("invoices")
