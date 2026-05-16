"""add profile_versions table

Phase 3 wave 1 (task AAA) — back the cloud-sync snapshot story described
in ``docs/ARCHITECTURE`` §2.7. Adds a single ``profile_versions`` table
that records every snapshot of a profile's ``user_data_dir`` uploaded to
S3-compatible object storage. Each row points at one immutable object
keyed by ``storage_key`` (e.g. ``tenants/{t}/profiles/{p}/v{n}.tar.zst``)
and carries the byte size + sha256 needed to verify integrity on
download.

This migration is intentionally infrastructure-only:

* The browser_manager / launch flow does NOT yet create rows here — that
  wiring lands in a follow-up wave (agent BBB).
* No router exposes the table yet — the REST surface comes in a later
  wave.

Versioning is monotonic per profile (``UNIQUE (profile_id, version)``);
the data layer (``backend.db_versions.create_version``) computes the
next number as ``MAX(version) + 1``. ``ON DELETE CASCADE`` from
``profiles(id)`` ensures snapshots are cleaned up with their parent
profile; the optional ``created_by_session_id`` FK uses ``SET NULL`` so
deleting a session doesn't orphan the snapshot row that captured its
final state.

Revision ID: 0013_add_profile_versions
Revises: 0012_rls_restrictive
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_add_profile_versions"
down_revision: Union[str, Sequence[str], None] = "0012_rls_restrictive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profile_versions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Monotonic per-profile snapshot number (1, 2, 3, ...). The data
        # layer derives ``next = MAX(version) + 1`` inside the same txn.
        sa.Column("version", sa.Integer(), nullable=False),
        # S3 object key — opaque TEXT here; format owned by
        # ``backend.storage.make_profile_snapshot_key``.
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        # Hex sha256 of the uploaded blob, for integrity check on download.
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Auditing: who / which session produced this snapshot. Both nullable
        # because background workers (e.g. periodic sync) may snapshot
        # without an interactive user/session.
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
        sa.Column(
            "created_by_session_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("profile_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "profile_id", "version", name="uq_profile_versions_profile_version"
        ),
    )
    op.create_index(
        "ix_profile_versions_profile_id",
        "profile_versions",
        ["profile_id"],
    )
    # DESC index for the common "latest first" listing query.
    op.execute(
        "CREATE INDEX ix_profile_versions_created_at "
        "ON profile_versions (created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_profile_versions_created_at")
    op.drop_index(
        "ix_profile_versions_profile_id", table_name="profile_versions"
    )
    op.drop_table("profile_versions")
