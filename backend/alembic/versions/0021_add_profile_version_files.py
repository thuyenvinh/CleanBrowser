"""add profile_version_files + diff-snapshot columns on profile_versions

Phase 8 wave 1 — back the file-level diff-snapshot story that replaces the
"tar+zstd the whole user_data_dir every stop" behaviour with an
incremental sync. Two pieces:

1. ``profile_version_files`` table — one row per file captured in a
   snapshot, recording its path (relative to ``user_data_dir``), the
   SHA-256 of its contents, and its size in bytes. The
   ``(version_id, path)`` composite primary key makes "what files did
   version X contain?" a single index seek, and the secondary
   ``ix_profile_version_files_sha256`` lets a future content-addressed
   store dedupe identical blobs across profiles.

2. Two new columns on ``profile_versions``:

   * ``snapshot_kind`` (TEXT NOT NULL DEFAULT 'full') — either ``'full'``
     (the whole user_data_dir is in this object) or ``'diff'`` (only
     files changed vs ``parent_version_id``). Defaulting to ``'full'``
     keeps every pre-existing row correctly classified without a data
     migration.
   * ``parent_version_id`` (UUID, nullable, ``ON DELETE SET NULL``) —
     for diff rows, the immediate ancestor whose state the diff applies
     on top of. ``SET NULL`` (not CASCADE) so deleting an old full
     snapshot doesn't silently nuke every descendant diff; restore code
     surfaces the broken chain instead.

This migration is infrastructure-only — ``browser_manager`` is NOT
switched over to ``snapshot_to_storage_diff`` in this wave; that
adoption is gated behind a separate change so we can land the schema and
the helper code first, then flip the call-site once verified.

Revision ID: 0021_add_profile_version_files
Revises: 0020_add_overage
Create Date: 2026-05-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_add_profile_version_files"
down_revision: Union[str, Sequence[str], None] = "0020_add_overage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profile_version_files",
        sa.Column(
            "version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("profile_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Path relative to ``user_data_dir`` (forward-slash separated, no
        # leading slash). The diff packer joins this with the local udir
        # at restore time, so anything absolute / containing ``..`` would
        # be a path-traversal footgun — sanitised at the application layer.
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "version_id", "path", name="pk_profile_version_files"
        ),
    )
    # Lookup by content hash — enables dedupe across versions/profiles
    # in a later wave (CAS object store) without a follow-up migration.
    op.create_index(
        "ix_profile_version_files_sha256",
        "profile_version_files",
        ["sha256"],
    )

    # Classify each snapshot row. Existing rows are all full snapshots
    # (the only kind that existed before this migration), so the server
    # default of 'full' correctly back-fills them.
    op.add_column(
        "profile_versions",
        sa.Column(
            "snapshot_kind",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'full'"),
        ),
    )
    # Parent pointer for diff rows. NULL means "no parent" (always true
    # for full snapshots; possible for diff rows whose chain was broken
    # by an upstream delete). SET NULL on parent delete so we don't
    # cascade-wipe a long history when an old full is GC'd.
    op.add_column(
        "profile_versions",
        sa.Column(
            "parent_version_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("profile_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("profile_versions", "parent_version_id")
    op.drop_column("profile_versions", "snapshot_kind")
    op.drop_index(
        "ix_profile_version_files_sha256",
        table_name="profile_version_files",
    )
    op.drop_table("profile_version_files")
