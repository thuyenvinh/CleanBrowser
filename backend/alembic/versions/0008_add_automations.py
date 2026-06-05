"""add automation tables (automations, versions, runs, schedules)

Phase 4 (task CC) — scaffold the Automation/RPA engine described in
``docs/ARCHITECTURE`` §2.6. Adds four tables that the future automation
interpreter / scheduler / worker will adopt; nothing in the API layer is
wired yet (CRUD module + Pydantic models land alongside this migration but
no router consumes them).

Shape mirrors :mod:`backend.alembic.versions.0006_add_proxies` for
consistency: ``id`` UUID app-layer, ``created_at`` server defaults,
``workspace_id`` cascade from :class:`workspaces`. The ``profile_id`` FKs
are ``ON DELETE SET NULL`` for ``automation_runs`` (so deleting a profile
preserves the run history for audit) and ``ON DELETE CASCADE`` for
``automation_schedules`` (a schedule pinned to a deleted profile is
dead-on-arrival).

Note: ``automations.latest_version_id`` is a circular-ish FK back to
``automation_versions.id``. It is added as a *separate* ALTER after both
tables exist; the column is nullable (no version yet at creation time) and
ON DELETE SET NULL (deleting the last version just clears the pointer).

Revision ID: 0008_add_automations
Revises: 0007_profile_proxy_id
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_add_automations"
down_revision: Union[str, Sequence[str], None] = "0007_profile_proxy_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------- automations
    op.create_table(
        "automations",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # kind ∈ {'flow','script'} — validated in the app layer.
        sa.Column("kind", sa.Text(), nullable=False),
        # FK wired below once automation_versions exists.
        sa.Column(
            "latest_version_id",
            postgresql.UUID(as_uuid=False),
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
        "ix_automations_workspace_id", "automations", ["workspace_id"]
    )

    # -------------------------------------------------- automation_versions
    op.create_table(
        "automation_versions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "automation_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("automations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Monotonic per-automation version counter (1, 2, 3...). The app
        # layer computes max(version) + 1 and the UNIQUE constraint guards
        # against concurrent inserts.
        sa.Column("version", sa.Integer(), nullable=False),
        # Duplicated from parent for fast lookup at run-dispatch time
        # (avoid a JOIN just to know if a row carries DSL or code).
        sa.Column("kind", sa.Text(), nullable=False),
        # Populated when kind='flow'.
        sa.Column(
            "dsl_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        # Populated when kind='script'.
        # script_language ∈ {'typescript','python'}.
        sa.Column("script_language", sa.Text(), nullable=True),
        sa.Column("script_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # NOT FK'd — we keep historical rows even if the user is deleted
        # (audit-style). Nullable for system-created versions (import,
        # migrate, marketplace install).
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "automation_id", "version", name="uq_automation_versions_a_v"
        ),
    )
    op.create_index(
        "ix_automation_versions_automation_id",
        "automation_versions",
        ["automation_id"],
    )

    # Wire the back-pointer now that both sides exist.
    op.create_foreign_key(
        "fk_automations_latest_version",
        source_table="automations",
        referent_table="automation_versions",
        local_cols=["latest_version_id"],
        remote_cols=["id"],
        ondelete="SET NULL",
    )

    # ------------------------------------------------------ automation_runs
    op.create_table(
        "automation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "automation_version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey(
                "automation_versions.id", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # status ∈ {'queued','running','success','failure','cancelled'}.
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "ended_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        # Phase 4 phase 1: inline TEXT. Phase 5: store an S3 key instead and
        # stream the log there from the worker.
        sa.Column("log_text", sa.Text(), nullable=True),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        # triggered_by ∈ {'manual','schedule','webhook','api'}.
        sa.Column(
            "triggered_by",
            sa.Text(),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "triggered_by_user_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_automation_runs_version_id_started",
        "automation_runs",
        ["automation_version_id", sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_automation_runs_profile_id", "automation_runs", ["profile_id"]
    )
    # Partial index for the scheduler/worker hot path: scanning queued or
    # currently-running rows. Keeps the index tiny vs. all historical runs.
    op.create_index(
        "ix_automation_runs_status_active",
        "automation_runs",
        ["status"],
        postgresql_where=sa.text("status IN ('queued','running')"),
    )

    # ------------------------------------------------- automation_schedules
    op.create_table(
        "automation_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "automation_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("automations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("cron", sa.Text(), nullable=False),
        sa.Column(
            "timezone", sa.Text(), nullable=False, server_default="UTC"
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "next_fire_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_fire_at",
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
    # Reconcile loop hot path: "what's due to fire?". Partial on enabled
    # so disabled schedules don't bloat the index.
    op.create_index(
        "ix_automation_schedules_next_fire",
        "automation_schedules",
        ["next_fire_at"],
        postgresql_where=sa.text("enabled = true"),
    )
    op.create_index(
        "ix_automation_schedules_automation_id",
        "automation_schedules",
        ["automation_id"],
    )


def downgrade() -> None:
    # Reverse order: schedules → runs → break circular FK → versions → automations.
    op.drop_index(
        "ix_automation_schedules_automation_id",
        table_name="automation_schedules",
    )
    op.drop_index(
        "ix_automation_schedules_next_fire",
        table_name="automation_schedules",
    )
    op.drop_table("automation_schedules")

    op.drop_index(
        "ix_automation_runs_status_active", table_name="automation_runs"
    )
    op.drop_index(
        "ix_automation_runs_profile_id", table_name="automation_runs"
    )
    op.drop_index(
        "ix_automation_runs_version_id_started",
        table_name="automation_runs",
    )
    op.drop_table("automation_runs")

    op.drop_constraint(
        "fk_automations_latest_version",
        "automations",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_automation_versions_automation_id",
        table_name="automation_versions",
    )
    op.drop_table("automation_versions")

    op.drop_index(
        "ix_automations_workspace_id", table_name="automations"
    )
    op.drop_table("automations")
