"""Profile snapshot version data layer.

Phase 3 wave 1 (task AAA) — CRUD over the ``profile_versions`` table
introduced by migration ``0013_add_profile_versions``. Each row indexes
one immutable snapshot uploaded to object storage by
:mod:`backend.storage`; together they let the cloud-sync flow described
in ``docs/ARCHITECTURE`` §2.7 list, restore, and delete previous states
of a profile's ``user_data_dir``.

Style mirrors :mod:`backend.db_proxy` and :mod:`backend.db_auth`:
synchronous psycopg2 on top of :func:`backend.database.get_db`,
returning plain ``dict`` rows with UUIDs stringified for JSON safety.
This module is intentionally NOT yet wired into any router or into
``browser_manager``; adoption happens in agent BBB's task and a later
wave's REST surface.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg2.extras

from .database import get_db


def create_version(
    profile_id: str,
    storage_key: str,
    size_bytes: int | None = None,
    sha256: str | None = None,
    created_by_user_id: str | None = None,
    created_by_session_id: str | None = None,
    notes: str | None = None,
) -> dict:
    """Insert a new snapshot row for ``profile_id``.

    The version number is computed inside the same transaction as
    ``MAX(existing) + 1`` so concurrent inserts can't collide on the
    ``UNIQUE (profile_id, version)`` constraint without one of them
    rolling back. Callers should retry on integrity errors (rare —
    snapshot writes are serialised per profile by the launch lifecycle).
    """

    version_id = str(uuid.uuid4())
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_v "
                "FROM profile_versions WHERE profile_id = %s",
                (profile_id,),
            )
            next_v = cur.fetchone()["next_v"]
            cur.execute(
                """
                INSERT INTO profile_versions
                    (id, profile_id, version, storage_key, size_bytes, sha256,
                     created_by_user_id, created_by_session_id, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    version_id,
                    profile_id,
                    next_v,
                    storage_key,
                    size_bytes,
                    sha256,
                    created_by_user_id,
                    created_by_session_id,
                    notes,
                ),
            )
            return _to_dict(cur.fetchone())


def list_versions(profile_id: str, limit: int = 50) -> list[dict]:
    """Return up to ``limit`` snapshots for ``profile_id``, newest first."""

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM profile_versions "
                "WHERE profile_id = %s "
                "ORDER BY version DESC LIMIT %s",
                (profile_id, limit),
            )
            return [_to_dict(r) for r in cur.fetchall()]


def get_version(version_id: str) -> dict | None:
    """Look up a single snapshot row by its ``id``."""

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM profile_versions WHERE id = %s",
                (version_id,),
            )
            row = cur.fetchone()
            return _to_dict(row) if row else None


def get_latest_version(profile_id: str) -> dict | None:
    """Return the most recent snapshot for ``profile_id``, or None.

    Used by the launch flow to decide which snapshot to restore from
    object storage when a profile is hydrated on a new worker.
    """

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM profile_versions "
                "WHERE profile_id = %s "
                "ORDER BY version DESC LIMIT 1",
                (profile_id,),
            )
            row = cur.fetchone()
            return _to_dict(row) if row else None


def delete_version(version_id: str) -> bool:
    """Delete one snapshot row. Returns True iff a row was removed.

    Note: this only drops the index row. The actual object in storage
    must be deleted separately via :func:`backend.storage.delete` —
    keeping the two operations distinct lets the caller decide
    ordering (delete-row-first to avoid orphaned objects, or
    delete-object-first if they prefer eager garbage collection).
    """

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM profile_versions WHERE id = %s",
                (version_id,),
            )
            return cur.rowcount > 0


def _to_dict(row: Any) -> dict:
    """Coerce a RealDictRow to a plain dict, stringifying UUIDs.

    UUID objects round-trip fine in psycopg2 but break ``json.dumps``
    without a custom encoder; stringifying at the data-layer boundary
    keeps the rest of the codebase free of UUID/str ambiguity.
    """

    d = dict(row)
    for k in (
        "id",
        "profile_id",
        "created_by_user_id",
        "created_by_session_id",
        # Added by migration 0021 for the diff-snapshot chain. Stringify
        # for the same json-safety reason as the other UUID columns.
        "parent_version_id",
    ):
        if d.get(k) is not None:
            d[k] = str(d[k])
    return d


# ---------------------------------------------------------------------------
# File-level diff snapshot helpers (migration 0021).
# ---------------------------------------------------------------------------
#
# These functions back the ``snapshot_to_storage_diff`` / ``restore_from_
# storage_diff`` flow in :mod:`backend.profile_snapshot`. They are kept
# here rather than in a sibling module so all writes against the
# ``profile_versions`` family of tables share one transactional surface
# and one connection-pool entry point (``get_db``).


def record_version_files(
    version_id: str, files: dict[str, dict]
) -> int:
    """Bulk-insert per-file metadata captured by a snapshot.

    ``files`` is the manifest's ``files`` dict — ``{rel_path: {sha256,
    size}}`` — produced by :func:`backend.snapshot_diff.pack_diff` (or
    by the equivalent walk for a full snapshot). One round-trip via
    :func:`psycopg2.extras.execute_values` so even a 50k-file Chromium
    profile lands in a single network hop. Returns the number of rows
    inserted (used by callers to log "snapshotted N files").
    """

    if not files:
        return 0
    from psycopg2.extras import execute_values

    rows = [
        (version_id, path, meta["sha256"], meta["size"])
        for path, meta in files.items()
    ]
    with get_db() as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                "INSERT INTO profile_version_files "
                "(version_id, path, sha256, size_bytes) VALUES %s",
                rows,
            )
    return len(rows)


def get_version_files(version_id: str) -> list[dict]:
    """Return ``[{path, sha256, size_bytes}, ...]`` for a snapshot.

    Used by the diff packer to learn the previous version's per-file
    SHA-256s without having to download and re-hash the parent blob.
    Returns an empty list (not None) for versions that have no recorded
    file metadata — e.g. snapshots created before migration 0021.
    """

    with get_db() as conn:
        with conn.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:
            cur.execute(
                "SELECT path, sha256, size_bytes "
                "FROM profile_version_files WHERE version_id = %s",
                (version_id,),
            )
            return [dict(r) for r in cur.fetchall()]


def mark_diff(version_id: str, parent_id: str) -> None:
    """Flip ``snapshot_kind`` to ``'diff'`` and link the parent version.

    Done as a separate UPDATE rather than passed into
    :func:`create_version` so the existing constructor signature (and
    the rows produced by full snapshots) stays untouched — callers that
    don't know about diffs keep working exactly as before.
    """

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE profile_versions "
                "SET snapshot_kind = 'diff', parent_version_id = %s "
                "WHERE id = %s",
                (parent_id, version_id),
            )


def find_full_snapshot_before(version_id: str) -> dict | None:
    """Walk back the parent chain from ``version_id`` to the nearest full.

    Returns the full-snapshot row, or ``None`` if the chain is broken
    (e.g. an ancestor was deleted and its ``parent_version_id`` SET
    NULL'd out from under us). The walk is bounded at 100 hops as a
    sanity guard against pathological chains; in practice ``full_every``
    in the snapshot scheduler keeps depth in the single digits.
    """

    cur_row = get_version(version_id)
    hops = 0
    while cur_row is not None and hops < 100:
        if cur_row.get("snapshot_kind", "full") == "full":
            return cur_row
        parent_id = cur_row.get("parent_version_id")
        if not parent_id:
            return None
        cur_row = get_version(parent_id)
        hops += 1
    return None
