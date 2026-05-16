"""add marketplace tables (marketplace_apps, tenant_app_installs)

Phase 6 (task PPP) — public catalog + install endpoint for the automation
app marketplace described in ``docs/ARCHITECTURE`` §2.6 (analogous to
GemStore's 50-module catalog and GPM's 2,000+ app store). Phase 1 ships
the public listing surface + clone-on-install flow only; revenue share,
paid apps, ratings, and creator self-publish all land in later waves.

Two tables:

* ``marketplace_apps`` — the catalog. ``slug`` is the human-stable id used
  in URLs; ``dsl_json`` / ``script_code`` carry the bundle payload that
  install-time copies into the workspace's ``automations`` table. A pair
  of partial indexes on ``is_public = true`` keeps category browse and
  popularity sort cheap regardless of how many draft/unlisted rows exist.

* ``tenant_app_installs`` — per-workspace install ledger. Pinned to the
  workspace (not just the tenant) so seat-scoped installs are possible
  later; ``automation_id`` is SET NULL on automation delete so the user
  deleting their cloned automation does not crash the marketplace UI.
  ``UNIQUE (workspace_id, app_id)`` makes the install endpoint idempotent
  via ``ON CONFLICT DO NOTHING``.

Seeds three official demo apps so the listing endpoint returns something
useful immediately on a fresh install (the marketplace UI would otherwise
land on an empty grid). UUIDs are static so reinstalling the migration
doesn't shift FKs already referenced by ``tenant_app_installs`` rows in
dev/staging environments.

Revision ID: 0018_add_marketplace
Revises: 0017_add_browser_type
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_add_marketplace"
down_revision: Union[str, Sequence[str], None] = "0017_add_browser_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────── marketplace_apps
    op.create_table(
        "marketplace_apps",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # markdown — rendered client-side on the app detail page.
        sa.Column("long_description", sa.Text(), nullable=True),
        sa.Column("icon_url", sa.Text(), nullable=True),
        # ∈ {'social','ecommerce','data','misc'}; validated app-layer only.
        sa.Column("category", sa.Text(), nullable=True),
        # Mirrors automations.kind — install time copies straight across.
        sa.Column(
            "kind", sa.Text(), nullable=False, server_default="flow"
        ),
        sa.Column(
            "dsl_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("script_language", sa.Text(), nullable=True),
        sa.Column("script_code", sa.Text(), nullable=True),
        sa.Column(
            "version", sa.Text(), nullable=False, server_default="1.0.0"
        ),
        sa.Column("creator_name", sa.Text(), nullable=True),
        sa.Column("creator_url", sa.Text(), nullable=True),
        sa.Column(
            "install_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "is_official",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        # Phase 6 phase 1: free-form list (e.g. ['network','storage']); the
        # install endpoint surfaces this so users can preview before clone.
        sa.Column(
            "required_permissions",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::TEXT[]"),
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
    # Partial indexes scoped to public rows — the browse surface only ever
    # filters/sorts on rows the user can actually see.
    op.create_index(
        "ix_marketplace_apps_category",
        "marketplace_apps",
        ["category"],
        postgresql_where=sa.text("is_public = true"),
    )
    op.create_index(
        "ix_marketplace_apps_install_count",
        "marketplace_apps",
        [sa.text("install_count DESC")],
        postgresql_where=sa.text("is_public = true"),
    )

    # ─────────────────────────────────────────────────── tenant_app_installs
    op.create_table(
        "tenant_app_installs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # RESTRICT (not CASCADE): deleting a marketplace app while installs
        # exist is operator error and should surface a clear FK violation
        # rather than silently wiping installed copies.
        sa.Column(
            "app_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("marketplace_apps.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        # SET NULL: user deleting the cloned automation should not break
        # the install ledger / uninstall path.
        sa.Column(
            "automation_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("automations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "installed_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Not FK'd — keep ledger when the user is deleted (audit-style).
        sa.Column(
            "installed_by_user_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        # Snapshot of the app's ``version`` at install time so a later app
        # bump doesn't retroactively change what's installed.
        sa.Column("app_version", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "workspace_id", "app_id", name="uq_tenant_app_installs_ws_app"
        ),
    )
    op.create_index(
        "ix_tenant_app_installs_tenant",
        "tenant_app_installs",
        ["tenant_id"],
    )

    # ─────────────────────────────────────────────────────────── seed demos
    # Three official demo flows — gives the marketplace UI immediate signal
    # on first launch. UUIDs hard-coded so repeated upgrade/downgrade in
    # dev stays stable.
    # Use exec_driver_sql so SQLAlchemy doesn't parse ``:1``/``:5000`` inside
    # the JSON literals as bind parameters.
    op.get_bind().exec_driver_sql(
        """
        INSERT INTO marketplace_apps (
            id, slug, name, description, category, kind,
            dsl_json, creator_name, is_official
        ) VALUES
        (
            '11111111-1111-1111-1111-111111111111',
            'visit-and-extract',
            'Visit & Extract Title',
            'Opens a URL and grabs the page title.',
            'data',
            'flow',
            '{"version":1,"start":"n1","nodes":[{"id":"n1","type":"goto_url","params":{"url":"https://example.com"},"next":["n2"]},{"id":"n2","type":"extract","params":{"selector":"h1","var":"title"},"next":["n3"]},{"id":"n3","type":"log","params":{"message":"Title extracted"}}]}'::jsonb,
            'CleanBrowser Team',
            true
        ),
        (
            '22222222-2222-2222-2222-222222222222',
            'fill-search-form',
            'Search & Click First Result',
            'Types a query into a search box and clicks the first result.',
            'misc',
            'flow',
            '{"version":1,"start":"n1","nodes":[{"id":"n1","type":"goto_url","params":{"url":"https://duckduckgo.com"},"next":["n2"]},{"id":"n2","type":"type","params":{"selector":"input[name=q]","text":"playwright"},"next":["n3"]},{"id":"n3","type":"wait","params":{"selector":"a[data-testid=result-title-a]","timeout":5000},"next":["n4"]},{"id":"n4","type":"click","params":{"selector":"a[data-testid=result-title-a]"}}]}'::jsonb,
            'CleanBrowser Team',
            true
        ),
        (
            '33333333-3333-3333-3333-333333333333',
            'scroll-and-screenshot',
            'Smooth Human Scroll',
            'Scrolls a page progressively to simulate human reading.',
            'misc',
            'flow',
            '{"version":1,"start":"n1","nodes":[{"id":"n1","type":"goto_url","params":{"url":"https://news.ycombinator.com"},"next":["n2"]},{"id":"n2","type":"wait_seconds","params":{"seconds":2},"next":["n3"]},{"id":"n3","type":"log","params":{"message":"Page loaded — manually scroll or extend flow"}}]}'::jsonb,
            'CleanBrowser Team',
            true
        )
        """
    )


def downgrade() -> None:
    # Reverse order: installs (FK to apps) → apps.
    op.drop_index(
        "ix_tenant_app_installs_tenant", table_name="tenant_app_installs"
    )
    op.drop_table("tenant_app_installs")

    op.drop_index(
        "ix_marketplace_apps_install_count", table_name="marketplace_apps"
    )
    op.drop_index(
        "ix_marketplace_apps_category", table_name="marketplace_apps"
    )
    op.drop_table("marketplace_apps")
