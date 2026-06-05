"""add automation_webhooks (token-authenticated trigger receivers)

Adds a fifth automation table for the public webhook receiver introduced
alongside this migration. The receiver lives at
``POST /api/webhooks/automation/{token}`` and authenticates purely on the
URL-embedded ``token`` — anyone holding the token can fire a run, so
deletion is the revocation mechanism and the partial index over
``token WHERE enabled = true`` lets us soft-disable a webhook without
dropping the row (preserves ``trigger_count`` history).

Schema notes:

* ``token`` — random ``secrets.token_urlsafe(32)`` (≈43 chars after
  base64-url encoding). Stored ``UNIQUE`` so the receiver can do a single
  indexed lookup; the partial index keyed off ``enabled = true`` is a
  hot-path optimisation for the high-volume lookup.
* ``profile_id`` — optional pre-bound profile. When present, the receiver
  enqueues the run with this profile already attached; when null the
  resulting run is profile-less (legal for ``script`` kind, will fail at
  execute time for ``flow`` kind). ``ON DELETE SET NULL`` so a profile
  deletion doesn't cascade-kill the webhook the user spent time wiring
  into Zapier / Make / Slack.
* ``trigger_count`` + ``last_triggered_at`` — surface in the UI so users
  can confirm the webhook is being hit (without having to dig through
  the run list). Updated in :func:`db_automation.mark_webhook_triggered`.

RLS: enabled and forced with the same permissive + restrictive double
policy pattern as the other automation tables. The webhook receiver
performs its lookup inside :func:`system_context` (the caller is
unauthenticated — there is no tenant on the request) which the
restrictive policy recognises as a bypass.

Revision ID: 0024_add_automation_webhooks
Revises: 0025_add_marketplace_earnings
Create Date: 2026-05-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_add_automation_webhooks"
down_revision: Union[str, Sequence[str], None] = "0025_add_marketplace_earnings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "automation_webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "automation_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("automations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column(
            "last_triggered_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "trigger_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    op.create_index(
        "ix_automation_webhooks_automation",
        "automation_webhooks",
        ["automation_id"],
    )

    # Partial index over ``token`` filtered to enabled rows — the receiver
    # only resolves enabled webhooks, so the hot lookup never reads
    # soft-disabled rows. UNIQUE on ``token`` (above) is still global so
    # toggling an old webhook back on can't collide with a freshly-minted
    # one that happens to share the (cryptographically improbable) token.
    op.execute(
        "CREATE INDEX ix_automation_webhooks_token "
        "ON automation_webhooks(token) WHERE enabled = true"
    )

    # ── RLS ──────────────────────────────────────────────────────────────
    # Mirror the pattern from 0009 + 0012: permissive policy granting
    # cross-tenant access to the matching tenant id, plus a restrictive
    # policy that also accepts the system bypass sentinel. The webhook
    # receiver runs its token lookup inside ``system_context`` — that's
    # the only code path that legitimately reads this table without a
    # tenant binding.
    op.execute("ALTER TABLE automation_webhooks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE automation_webhooks FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON automation_webhooks
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) IS NULL
            OR current_setting('app.current_tenant_id', true) = ''
            OR EXISTS (
                SELECT 1
                FROM automations a
                JOIN workspaces w ON w.id = a.workspace_id
                WHERE a.id = automation_webhooks.automation_id
                  AND w.tenant_id::text
                      = current_setting('app.current_tenant_id', true)
            )
        )
        """
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation_restrict ON automation_webhooks
        AS RESTRICTIVE
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true)
                = '00000000-0000-0000-0000-000000000000'
            OR EXISTS (
                SELECT 1
                FROM automations a
                JOIN workspaces w ON w.id = a.workspace_id
                WHERE a.id = automation_webhooks.automation_id
                  AND w.tenant_id::text
                      = current_setting('app.current_tenant_id', true)
            )
        )
        WITH CHECK (
            current_setting('app.current_tenant_id', true)
                = '00000000-0000-0000-0000-000000000000'
            OR EXISTS (
                SELECT 1
                FROM automations a
                JOIN workspaces w ON w.id = a.workspace_id
                WHERE a.id = automation_webhooks.automation_id
                  AND w.tenant_id::text
                      = current_setting('app.current_tenant_id', true)
            )
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation_restrict ON automation_webhooks"
    )
    op.execute(
        "DROP POLICY IF EXISTS tenant_isolation ON automation_webhooks"
    )
    op.execute("DROP INDEX IF EXISTS ix_automation_webhooks_token")
    op.drop_index(
        "ix_automation_webhooks_automation",
        table_name="automation_webhooks",
    )
    op.drop_table("automation_webhooks")
