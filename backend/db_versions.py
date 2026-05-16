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
    ):
        if d.get(k) is not None:
            d[k] = str(d[k])
    return d
