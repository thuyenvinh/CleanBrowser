"""PostgreSQL database operations for browser profiles.

This module replaces the previous SQLite implementation while preserving the
public API surface used by other backend modules:

    init_db()
    create_profile(name, fingerprint_seed=None, **fields) -> dict
    get_profile(profile_id) -> dict | None
    list_profiles() -> list[dict]
    update_profile(profile_id, **fields) -> dict | None
    delete_profile(profile_id) -> bool

Schema is owned by Alembic migrations (see ``backend/alembic``); ``init_db``
only validates connectivity. Parameter style is ``%s`` (psycopg2) instead of
``?``. ``launch_args`` is stored as native JSONB.
"""

from __future__ import annotations

import datetime
import json
import os
import random
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool

# Kept for backwards-compat with callers that derive paths (e.g. user_data_dir).
DATA_DIR = Path("/data")

_POOL: SimpleConnectionPool | None = None
_POOL_LOCK = threading.Lock()


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required "
            "(e.g. postgresql://user:pass@host:5432/dbname)"
        )
    return url


def _get_pool() -> SimpleConnectionPool:
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = SimpleConnectionPool(
                    minconn=1,
                    maxconn=int(os.environ.get("DATABASE_POOL_MAX", "10")),
                    dsn=_database_url(),
                )
    return _POOL


@contextmanager
def get_db():
    """Yield a psycopg2 connection backed by a process-wide pool.

    Connection is returned to the pool on exit. Caller is responsible for
    committing; on exception the connection is rolled back before return.
    """
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        pool.putconn(conn)


def init_db() -> None:
    """Verify the database is reachable. Schema is managed by Alembic."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "profiles").mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _row_to_profile(row: dict[str, Any]) -> dict[str, Any]:
    profile = dict(row)
    # launch_args is JSONB → psycopg2 returns a list/dict already; normalize.
    la = profile.get("launch_args")
    if la is None:
        profile["launch_args"] = []
    elif isinstance(la, str):
        try:
            profile["launch_args"] = json.loads(la)
        except json.JSONDecodeError:
            profile["launch_args"] = []
    # Stringify timestamps to ISO for parity with the old SQLite shape.
    for ts_col in ("created_at", "updated_at"):
        v = profile.get(ts_col)
        if isinstance(v, datetime.datetime):
            profile[ts_col] = v.isoformat()
    # Stringify id for parity (was TEXT in SQLite).
    if isinstance(profile.get("id"), uuid.UUID):
        profile["id"] = str(profile["id"])
    # workspace_id is UUID-typed in Postgres; psycopg2 returns ``uuid.UUID``
    # objects which Pydantic/JSON layers downstream don't always like. Mirror
    # the ``id`` normalisation. ``None`` stays ``None`` for legacy / orphan
    # profiles (see migration 0005).
    if isinstance(profile.get("workspace_id"), uuid.UUID):
        profile["workspace_id"] = str(profile["workspace_id"])
    # proxy_id (added in migration 0007) is also UUID-typed; mirror the
    # ``workspace_id`` normalisation so downstream serialisers see a str.
    if isinstance(profile.get("proxy_id"), uuid.UUID):
        profile["proxy_id"] = str(profile["proxy_id"])
    return profile


def create_profile(
    name: str,
    fingerprint_seed: int | None = None,
    workspace_id: str | None = None,
    proxy_id: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    profile_id = str(uuid.uuid4())
    seed = fingerprint_seed if fingerprint_seed is not None else random.randint(10000, 99999)
    user_data_dir = str(DATA_DIR / "profiles" / profile_id)
    now = _now()
    tags = fields.pop("tags", None) or []

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO profiles (
                    id, name, fingerprint_seed, proxy, timezone, locale, platform,
                    user_agent, screen_width, screen_height, gpu_vendor, gpu_renderer,
                    hardware_concurrency, humanize, human_preset, headless, geoip,
                    clipboard_sync, auto_launch, color_scheme, launch_args, notes,
                    user_data_dir, workspace_id, proxy_id, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)""",
                (
                    profile_id, name, seed,
                    fields.get("proxy"),
                    fields.get("timezone"),
                    fields.get("locale"),
                    fields.get("platform", "windows"),
                    fields.get("user_agent"),
                    fields.get("screen_width", 1920),
                    fields.get("screen_height", 1080),
                    fields.get("gpu_vendor"),
                    fields.get("gpu_renderer"),
                    fields.get("hardware_concurrency"),
                    bool(fields.get("humanize", False)),
                    fields.get("human_preset", "default"),
                    bool(fields.get("headless", False)),
                    bool(fields.get("geoip", False)),
                    bool(fields.get("clipboard_sync", True)),
                    bool(fields.get("auto_launch", False)),
                    fields.get("color_scheme"),
                    json.dumps(fields.get("launch_args") or []),
                    fields.get("notes"),
                    user_data_dir, workspace_id, proxy_id, now, now,
                ),
            )
            for t in tags:
                cur.execute(
                    "INSERT INTO profile_tags (profile_id, tag, color) VALUES (%s, %s, %s)",
                    (profile_id, t["tag"], t.get("color")),
                )
        conn.commit()

    return get_profile(profile_id)  # type: ignore[return-value]


def get_profile(profile_id: str) -> dict[str, Any] | None:
    try:
        uuid.UUID(str(profile_id))
    except (ValueError, AttributeError, TypeError):
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM profiles WHERE id = %s", (profile_id,))
            row = cur.fetchone()
            if not row:
                return None
            profile = _row_to_profile(row)
            cur.execute(
                "SELECT tag, color FROM profile_tags WHERE profile_id = %s",
                (profile_id,),
            )
            profile["tags"] = [dict(t) for t in cur.fetchall()]
            return profile


def list_profiles(
    workspace_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """List profiles, optionally scoped to a set of workspace ids.

    ``workspace_ids`` semantics — chosen so legacy / unauth call sites keep
    working without thinking about workspaces:

    * ``None``  → no filter at all; return every row (legacy AUTH_TOKEN
      mode, test suite, scripts hitting the API without a session).
    * ``[]``    → user has zero workspaces → return ``[]``. We short-circuit
      to avoid emitting a ``WHERE workspace_id IN ()`` which is invalid SQL.
    * non-empty list → ``WHERE workspace_id IN (...)``. Profiles whose
      ``workspace_id`` is ``NULL`` (orphans / legacy) are deliberately
      excluded — a workspace member must not see un-scoped profiles.
    """
    if workspace_ids is not None and len(workspace_ids) == 0:
        return []
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if workspace_ids is None:
                cur.execute("SELECT * FROM profiles ORDER BY created_at DESC")
            else:
                cur.execute(
                    "SELECT * FROM profiles WHERE workspace_id = ANY(%s::uuid[]) "
                    "ORDER BY created_at DESC",
                    (list(workspace_ids),),
                )
            rows = cur.fetchall()
            profiles: list[dict[str, Any]] = []
            for row in rows:
                profile = _row_to_profile(row)
                cur.execute(
                    "SELECT tag, color FROM profile_tags WHERE profile_id = %s",
                    (profile["id"],),
                )
                profile["tags"] = [dict(t) for t in cur.fetchall()]
                profiles.append(profile)
            return profiles


def update_profile(profile_id: str, **fields: Any) -> dict[str, Any] | None:
    try:
        uuid.UUID(str(profile_id))
    except (ValueError, AttributeError, TypeError):
        return None
    existing = get_profile(profile_id)
    if not existing:
        return None

    tags = fields.pop("tags", None)

    update_cols: list[str] = []
    update_vals: list[Any] = []

    # launch_args is JSONB; cast explicitly.
    if "launch_args" in fields:
        fields["launch_args"] = json.dumps(fields["launch_args"] or [])

    for col in (
        "name", "fingerprint_seed", "proxy", "timezone", "locale", "platform",
        "user_agent", "screen_width", "screen_height", "gpu_vendor", "gpu_renderer",
        "hardware_concurrency", "humanize", "human_preset", "headless", "geoip",
        "clipboard_sync", "auto_launch", "color_scheme", "launch_args", "notes",
        "workspace_id", "proxy_id",
    ):
        if col in fields:
            if col == "launch_args":
                update_cols.append(f"{col} = %s::jsonb")
            else:
                update_cols.append(f"{col} = %s")
            update_vals.append(fields[col])

    if update_cols:
        update_cols.append("updated_at = %s")
        update_vals.append(_now())
        update_vals.append(profile_id)
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE profiles SET {', '.join(update_cols)} WHERE id = %s",
                    update_vals,
                )
            conn.commit()

    if tags is not None:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM profile_tags WHERE profile_id = %s", (profile_id,))
                for t in tags:
                    cur.execute(
                        "INSERT INTO profile_tags (profile_id, tag, color) VALUES (%s, %s, %s)",
                        (profile_id, t["tag"], t.get("color")),
                    )
            conn.commit()

    return get_profile(profile_id)


def delete_profile(profile_id: str) -> bool:
    try:
        uuid.UUID(str(profile_id))
    except (ValueError, AttributeError, TypeError):
        return False
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM profiles WHERE id = %s", (profile_id,))
            rowcount = cur.rowcount
        conn.commit()
        return rowcount > 0


# ---------------------------------------------------------------------------
# profile_sessions
#
# Persistent record of every browser launch. Replaces ``BrowserManager.running``
# as the source of truth for "is profile X currently active?" — the in-memory
# dict is now just a cache for process handles. See docs/ARCHITECTURE §2.2.
# ---------------------------------------------------------------------------


def _row_to_session(row: dict[str, Any]) -> dict[str, Any]:
    session = dict(row)
    if isinstance(session.get("id"), uuid.UUID):
        session["id"] = str(session["id"])
    if isinstance(session.get("profile_id"), uuid.UUID):
        session["profile_id"] = str(session["profile_id"])
    for ts_col in ("started_at", "ended_at"):
        v = session.get(ts_col)
        if isinstance(v, datetime.datetime):
            session[ts_col] = v.isoformat()
    return session


def create_session(
    profile_id: str,
    display_num: int | None = None,
    ws_port: int | None = None,
    cdp_port: int | None = None,
    worker_id: str = "local",
) -> dict[str, Any]:
    """Insert a new session row with status='starting'.

    The partial unique index ``ux_profile_sessions_one_active`` raises
    ``psycopg2.errors.UniqueViolation`` if another active session for this
    profile already exists.
    """
    session_id = str(uuid.uuid4())
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO profile_sessions (
                    id, profile_id, worker_id, status,
                    display_num, ws_port, cdp_port
                ) VALUES (%s, %s, %s, 'starting', %s, %s, %s)
                RETURNING *""",
                (session_id, profile_id, worker_id, display_num, ws_port, cdp_port),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_session(row)


def mark_session_running(session_id: str) -> None:
    """Transition a session from 'starting' to 'running'."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE profile_sessions SET status = 'running' WHERE id = %s",
                (session_id,),
            )
        conn.commit()


def end_session(
    session_id: str,
    status: str = "stopped",
    error_message: str | None = None,
) -> None:
    """Mark a session as ended. ``status`` should be 'stopped' or 'crashed'.

    Idempotent — repeated calls on an already-ended session are a no-op
    (``ended_at`` is preserved).
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE profile_sessions
                   SET status = %s,
                       ended_at = now(),
                       error_message = COALESCE(%s, error_message)
                   WHERE id = %s AND ended_at IS NULL""",
                (status, error_message, session_id),
            )
        conn.commit()


def get_active_session_for_profile(profile_id: str) -> dict[str, Any] | None:
    """Return the current active (``ended_at IS NULL``) session for a profile."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM profile_sessions
                   WHERE profile_id = %s AND ended_at IS NULL
                   LIMIT 1""",
                (profile_id,),
            )
            row = cur.fetchone()
            return _row_to_session(row) if row else None


def list_active_sessions() -> list[dict[str, Any]]:
    """List every session with ``ended_at IS NULL``. Used for startup recovery."""
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM profile_sessions
                   WHERE ended_at IS NULL
                   ORDER BY started_at ASC"""
            )
            return [_row_to_session(r) for r in cur.fetchall()]


def cleanup_stale_sessions() -> int:
    """Mark every active session as crashed.

    Called on container/server startup: any session row left active across a
    restart is by definition orphaned, because the process that owned it has
    been killed.

    Returns the number of rows updated.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE profile_sessions
                   SET status = 'crashed',
                       ended_at = now(),
                       error_message = COALESCE(
                           error_message,
                           'process killed by server restart'
                       )
                   WHERE ended_at IS NULL"""
            )
            count = cur.rowcount
        conn.commit()
        return count
