"""Automation/RPA data layer.

Workspace-scoped CRUD for the four tables introduced by migration
``0008_add_automations`` — ``automations``, ``automation_versions``,
``automation_runs``, ``automation_schedules``. Mirrors the style of
:mod:`backend.db_proxy` / :mod:`backend.db_auth`: synchronous psycopg2 on
top of :func:`backend.database.get_db`, returning plain ``dict`` rows
(``RealDictCursor``). Not yet wired into any router or worker — the
automation engine (interpreter, scheduler, worker) lands in separate
follow-up tasks.

See ``docs/ARCHITECTURE`` §2.6.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

import psycopg2.extras

from .database import get_db

# ---------------------------------------------------------------------------
# Constants / validation
# ---------------------------------------------------------------------------

VALID_KINDS: frozenset[str] = frozenset({"flow", "script"})
VALID_SCRIPT_LANGUAGES: frozenset[str] = frozenset({"typescript", "python"})
VALID_RUN_STATUSES: frozenset[str] = frozenset(
    {"queued", "running", "success", "failure", "cancelled"}
)
# ``success`` / ``failure`` / ``cancelled`` — i.e. runs that have reached
# a sink state and should NOT be touched by the worker any more.
_TERMINAL_RUN_STATUSES: frozenset[str] = frozenset(
    {"success", "failure", "cancelled"}
)
VALID_TRIGGERS: frozenset[str] = frozenset(
    {"manual", "schedule", "webhook", "api"}
)

# Columns the app layer is allowed to update via ``update_automation``.
_AUTOMATION_UPDATABLE: frozenset[str] = frozenset({"name", "description"})

# Columns the app layer is allowed to update via ``update_schedule``.
_SCHEDULE_UPDATABLE: frozenset[str] = frozenset(
    {"cron", "timezone", "enabled", "profile_id"}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise ValueError(
            f"invalid automation kind {kind!r}; must be one of "
            f"{sorted(VALID_KINDS)}"
        )


def _require_script_language(language: str | None) -> None:
    if language is not None and language not in VALID_SCRIPT_LANGUAGES:
        raise ValueError(
            f"invalid script_language {language!r}; must be one of "
            f"{sorted(VALID_SCRIPT_LANGUAGES)}"
        )


def _require_run_status(status: str) -> None:
    if status not in VALID_RUN_STATUSES:
        raise ValueError(
            f"invalid run status {status!r}; must be one of "
            f"{sorted(VALID_RUN_STATUSES)}"
        )


def _require_trigger(triggered_by: str) -> None:
    if triggered_by not in VALID_TRIGGERS:
        raise ValueError(
            f"invalid triggered_by {triggered_by!r}; must be one of "
            f"{sorted(VALID_TRIGGERS)}"
        )


def _safe_uuid(value: Any) -> bool:
    """Return ``True`` iff ``value`` parses as a UUID. Used to short-circuit
    lookups on garbage input so we never round-trip an obviously invalid id
    to Postgres (which would just raise a DataError)."""
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    """Normalise a psycopg2 RealDict row for JSON serialisation.

    Stringifies UUIDs / datetimes (parity with :mod:`db_auth` and
    :mod:`db_proxy`). JSONB columns are returned by psycopg2 as plain
    ``dict`` already, so nothing extra needed there.
    """
    if row is None:
        return None
    out = dict(row)
    for key, val in list(out.items()):
        if isinstance(val, uuid.UUID):
            out[key] = str(val)
        elif isinstance(val, datetime.datetime):
            out[key] = val.isoformat()
    return out


def _json_param(value: Any) -> Any:
    """Wrap a ``dict``/``list`` so psycopg2 sends it as JSONB.

    psycopg2 will not implicitly adapt a plain ``dict``; using
    :class:`psycopg2.extras.Json` ensures the value is serialised once on
    the client and inserted as JSONB.
    """
    if value is None:
        return None
    return psycopg2.extras.Json(value)


# ---------------------------------------------------------------------------
# automations
# ---------------------------------------------------------------------------


def create_automation(
    workspace_id: str,
    name: str,
    kind: str,
    description: str | None = None,
) -> dict[str, Any]:
    """Insert an :class:`automations` row. ``latest_version_id`` stays NULL
    until the first version is created via :func:`create_version`."""
    _require_kind(kind)
    automation_id = str(uuid.uuid4())
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO automations
                       (id, workspace_id, name, kind, description)
                   VALUES (%s, %s, %s, %s, %s)
                   RETURNING *""",
                (automation_id, workspace_id, name, kind, description),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


def get_automation(automation_id: str) -> dict[str, Any] | None:
    if not _safe_uuid(automation_id):
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM automations WHERE id = %s", (automation_id,)
            )
            return _row_to_dict(cur.fetchone())


def list_automations(workspace_id: str) -> list[dict[str, Any]]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM automations
                   WHERE workspace_id = %s
                   ORDER BY created_at ASC""",
                (workspace_id,),
            )
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


def update_automation(
    automation_id: str, **fields: Any
) -> dict[str, Any] | None:
    """Patch ``name`` / ``description``. Unknown columns are ignored.

    Returns the updated record, or ``None`` if no row matched.
    """
    if not _safe_uuid(automation_id):
        return None
    update_cols: list[str] = []
    update_vals: list[Any] = []
    for col in _AUTOMATION_UPDATABLE:
        if col in fields:
            update_cols.append(f"{col} = %s")
            update_vals.append(fields[col])
    if not update_cols:
        return get_automation(automation_id)
    update_cols.append("updated_at = now()")
    update_vals.append(automation_id)
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"UPDATE automations SET {', '.join(update_cols)} "
                f"WHERE id = %s RETURNING *",
                update_vals,
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)


def delete_automation(automation_id: str) -> bool:
    """Hard-delete an automation. Cascades to versions / runs / schedules."""
    if not _safe_uuid(automation_id):
        return False
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM automations WHERE id = %s", (automation_id,)
            )
            removed = cur.rowcount > 0
        conn.commit()
    return removed


# ---------------------------------------------------------------------------
# automation_versions
# ---------------------------------------------------------------------------


def create_version(
    automation_id: str,
    kind: str,
    dsl_json: dict | None = None,
    script_language: str | None = None,
    script_code: str | None = None,
    created_by_user_id: str | None = None,
) -> dict[str, Any]:
    """Append a new version row to ``automation_id`` and bump
    ``automations.latest_version_id`` to point at it.

    The whole operation runs in a single transaction so a concurrent caller
    can't end up with a stale ``latest_version_id`` pointer. The version
    counter is ``max(version) + 1`` (default 1 for the very first version).

    Validates ``kind`` matches the parent automation's kind — divergence
    would silently break the dispatch path that trusts the column.
    """
    if not _safe_uuid(automation_id):
        raise ValueError(f"invalid automation_id {automation_id!r}")
    _require_kind(kind)
    _require_script_language(script_language)

    version_id = str(uuid.uuid4())

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Verify parent exists and kind matches.
            cur.execute(
                "SELECT kind FROM automations WHERE id = %s FOR UPDATE",
                (automation_id,),
            )
            parent = cur.fetchone()
            if parent is None:
                raise LookupError(
                    f"automation {automation_id!r} not found"
                )
            if parent["kind"] != kind:
                raise ValueError(
                    f"version kind {kind!r} does not match automation "
                    f"kind {parent['kind']!r}"
                )

            # Next version number.
            cur.execute(
                """SELECT COALESCE(MAX(version), 0) + 1 AS next_version
                   FROM automation_versions
                   WHERE automation_id = %s""",
                (automation_id,),
            )
            next_version = int(cur.fetchone()["next_version"])

            cur.execute(
                """INSERT INTO automation_versions (
                       id, automation_id, version, kind,
                       dsl_json, script_language, script_code,
                       created_by_user_id
                   ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (
                    version_id,
                    automation_id,
                    next_version,
                    kind,
                    _json_param(dsl_json),
                    script_language,
                    script_code,
                    created_by_user_id,
                ),
            )
            row = cur.fetchone()

            cur.execute(
                """UPDATE automations
                   SET latest_version_id = %s, updated_at = now()
                   WHERE id = %s""",
                (version_id, automation_id),
            )
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


def get_version(version_id: str) -> dict[str, Any] | None:
    if not _safe_uuid(version_id):
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM automation_versions WHERE id = %s",
                (version_id,),
            )
            return _row_to_dict(cur.fetchone())


def list_versions(automation_id: str) -> list[dict[str, Any]]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM automation_versions
                   WHERE automation_id = %s
                   ORDER BY version ASC""",
                (automation_id,),
            )
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# automation_runs
# ---------------------------------------------------------------------------


def create_run(
    automation_version_id: str,
    profile_id: str | None = None,
    triggered_by: str = "manual",
    triggered_by_user_id: str | None = None,
) -> dict[str, Any]:
    """Enqueue a new run row in ``status='queued'``.

    The worker is expected to pick it up via :func:`list_queued_runs`, flip
    it to ``running`` with :func:`mark_run_running`, then terminate via
    :func:`end_run`.
    """
    _require_trigger(triggered_by)
    run_id = str(uuid.uuid4())
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO automation_runs (
                       id, automation_version_id, profile_id, status,
                       triggered_by, triggered_by_user_id
                   ) VALUES (%s, %s, %s, 'queued', %s, %s)
                   RETURNING *""",
                (
                    run_id,
                    automation_version_id,
                    profile_id,
                    triggered_by,
                    triggered_by_user_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


def mark_run_running(run_id: str) -> None:
    """Flip ``queued`` → ``running``. No-op if already running/terminal."""
    if not _safe_uuid(run_id):
        return
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE automation_runs
                   SET status = 'running', started_at = now()
                   WHERE id = %s AND status = 'queued'""",
                (run_id,),
            )
        conn.commit()


def end_run(
    run_id: str,
    status: str,
    result_json: dict | None = None,
    error_message: str | None = None,
    log_text: str | None = None,
) -> None:
    """Terminate a run by setting ``status`` + ``ended_at = now()``.

    ``status`` MUST be one of the terminal states
    (``success`` / ``failure`` / ``cancelled``); anything else raises
    ``ValueError`` to surface caller bugs early (e.g. accidentally passing
    ``queued`` here would silently clobber ``ended_at``).

    ``log_text`` overwrites any prior log; use :func:`append_run_log` for
    incremental streaming during the run.
    """
    if status not in _TERMINAL_RUN_STATUSES:
        raise ValueError(
            f"end_run status must be terminal {sorted(_TERMINAL_RUN_STATUSES)}, "
            f"got {status!r}"
        )
    if not _safe_uuid(run_id):
        return
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE automation_runs SET
                       status = %s,
                       ended_at = now(),
                       result_json = COALESCE(%s, result_json),
                       error_message = COALESCE(%s, error_message),
                       log_text = COALESCE(%s, log_text)
                   WHERE id = %s""",
                (
                    status,
                    _json_param(result_json),
                    error_message,
                    log_text,
                    run_id,
                ),
            )
        conn.commit()


def get_run(run_id: str) -> dict[str, Any] | None:
    if not _safe_uuid(run_id):
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM automation_runs WHERE id = %s", (run_id,)
            )
            return _row_to_dict(cur.fetchone())


def list_runs(
    automation_id: str | None = None,
    version_id: str | None = None,
    profile_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List runs, newest-first. Filters are AND-ed.

    ``automation_id`` is resolved via a JOIN against ``automation_versions``
    (runs only carry the version FK directly). Passing none of the filters
    returns the global newest-first feed — useful for admin / debugging,
    paginate with ``limit``/``offset``.
    """
    where: list[str] = []
    params: list[Any] = []
    sql = "SELECT r.* FROM automation_runs r"

    if automation_id is not None:
        sql += " JOIN automation_versions v ON v.id = r.automation_version_id"
        where.append("v.automation_id = %s")
        params.append(automation_id)
    if version_id is not None:
        where.append("r.automation_version_id = %s")
        params.append(version_id)
    if profile_id is not None:
        where.append("r.profile_id = %s")
        params.append(profile_id)

    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.started_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


def append_run_log(run_id: str, line: str) -> None:
    """Append ``line`` (plus trailing newline) to ``log_text``.

    Uses ``COALESCE`` so the first append doesn't have to read-then-write.
    Cheap enough at Phase 4 phase 1 scale; once logs move to S3 (Phase 5)
    this function should disappear in favour of a streaming writer.
    """
    if not _safe_uuid(run_id):
        return
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE automation_runs
                   SET log_text = COALESCE(log_text, '') || %s
                   WHERE id = %s""",
                (line + "\n", run_id),
            )
        conn.commit()


def list_queued_runs(limit: int = 50) -> list[dict[str, Any]]:
    """Return up to ``limit`` runs in ``status='queued'``, oldest-first.

    Used by the scheduler/worker dispatch loop. The partial index
    ``ix_automation_runs_status_active`` keeps this scan O(queued)
    regardless of how many historical runs exist.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM automation_runs
                   WHERE status = 'queued'
                   ORDER BY started_at ASC
                   LIMIT %s""",
                (limit,),
            )
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


def cleanup_stale_runs() -> int:
    """Mark orphaned ``running`` runs as ``failure``.

    Called at process startup: if the worker died mid-run, the row is stuck
    in ``running`` forever. This sweeps such rows to ``failure`` with a
    fixed error string so operators can see what happened. Returns the
    number of rows transitioned.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE automation_runs
                   SET status = 'failure',
                       ended_at = now(),
                       error_message = COALESCE(
                           error_message,
                           'worker terminated before run completed'
                       )
                   WHERE status = 'running'""",
            )
            rowcount = cur.rowcount
        conn.commit()
    return rowcount


# ---------------------------------------------------------------------------
# automation_schedules
# ---------------------------------------------------------------------------


def create_schedule(
    automation_id: str,
    cron: str,
    profile_id: str | None = None,
    timezone: str = "UTC",
    enabled: bool = True,
) -> dict[str, Any]:
    """Create a cron schedule for ``automation_id``.

    The reconcile loop is expected to compute ``next_fire_at`` via
    :func:`set_schedule_next_fire` shortly after creation; we don't compute
    it here because parsing cron requires a dependency this layer doesn't
    want to take on (croniter / apscheduler) — that lives in the engine.
    """
    schedule_id = str(uuid.uuid4())
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO automation_schedules (
                       id, automation_id, profile_id, cron, timezone, enabled
                   ) VALUES (%s, %s, %s, %s, %s, %s)
                   RETURNING *""",
                (
                    schedule_id,
                    automation_id,
                    profile_id,
                    cron,
                    timezone,
                    enabled,
                ),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


def get_schedule(schedule_id: str) -> dict[str, Any] | None:
    if not _safe_uuid(schedule_id):
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM automation_schedules WHERE id = %s",
                (schedule_id,),
            )
            return _row_to_dict(cur.fetchone())


def list_schedules(
    automation_id: str | None = None, due_only: bool = False
) -> list[dict[str, Any]]:
    """List schedules. With ``due_only=True``, return only enabled rows
    whose ``next_fire_at`` is non-NULL and in the past (i.e. ready to fire
    *now*). The reconcile loop uses this to pick work each tick.

    With no filters, returns every schedule — handy for the management UI.
    """
    where: list[str] = []
    params: list[Any] = []
    if automation_id is not None:
        where.append("automation_id = %s")
        params.append(automation_id)
    if due_only:
        where.append("enabled = true")
        where.append("next_fire_at IS NOT NULL")
        where.append("next_fire_at <= now()")

    sql = "SELECT * FROM automation_schedules"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at ASC"
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


def update_schedule(
    schedule_id: str, **fields: Any
) -> dict[str, Any] | None:
    """Patch ``cron`` / ``timezone`` / ``enabled`` / ``profile_id``.

    Note: ``next_fire_at`` / ``last_fire_at`` are deliberately NOT in the
    updatable set — they're managed by :func:`set_schedule_next_fire` /
    :func:`mark_schedule_fired` to keep accidental clobbers out of CRUD.
    """
    if not _safe_uuid(schedule_id):
        return None
    update_cols: list[str] = []
    update_vals: list[Any] = []
    for col in _SCHEDULE_UPDATABLE:
        if col in fields:
            update_cols.append(f"{col} = %s")
            update_vals.append(fields[col])
    if not update_cols:
        return get_schedule(schedule_id)
    update_vals.append(schedule_id)
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"UPDATE automation_schedules SET {', '.join(update_cols)} "
                f"WHERE id = %s RETURNING *",
                update_vals,
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)


def delete_schedule(schedule_id: str) -> bool:
    if not _safe_uuid(schedule_id):
        return False
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM automation_schedules WHERE id = %s",
                (schedule_id,),
            )
            removed = cur.rowcount > 0
        conn.commit()
    return removed


def set_schedule_next_fire(
    schedule_id: str, next_fire_at: datetime.datetime | None
) -> None:
    """Update only ``next_fire_at``. The engine calls this after computing
    the next cron occurrence in the schedule's timezone."""
    if not _safe_uuid(schedule_id):
        return
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE automation_schedules
                   SET next_fire_at = %s
                   WHERE id = %s""",
                (next_fire_at, schedule_id),
            )
        conn.commit()


def mark_schedule_fired(
    schedule_id: str, fired_at: datetime.datetime
) -> None:
    """Record that the schedule fired at ``fired_at`` (sets
    ``last_fire_at``). The reconcile loop should follow up by computing
    the next occurrence and calling :func:`set_schedule_next_fire`."""
    if not _safe_uuid(schedule_id):
        return
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE automation_schedules
                   SET last_fire_at = %s
                   WHERE id = %s""",
                (fired_at, schedule_id),
            )
        conn.commit()


def list_due_schedules(now: datetime.datetime) -> list[dict[str, Any]]:
    """Return enabled schedules whose ``next_fire_at <= now`` (NULL excluded).

    Worker-side counterpart of :func:`list_schedules` with ``due_only=True``,
    but parameterised on ``now`` so the caller can pass an explicit UTC
    timestamp (and tests can freeze time). Capped at 100 rows per tick to
    bound the work the reconcile loop does in a single pass.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM automation_schedules
                   WHERE enabled = true
                     AND next_fire_at IS NOT NULL
                     AND next_fire_at <= %s
                   ORDER BY next_fire_at
                   LIMIT 100""",
                (now,),
            )
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


__all__ = [
    "VALID_KINDS",
    "VALID_SCRIPT_LANGUAGES",
    "VALID_RUN_STATUSES",
    "VALID_TRIGGERS",
    # automations
    "create_automation",
    "get_automation",
    "list_automations",
    "update_automation",
    "delete_automation",
    # versions
    "create_version",
    "get_version",
    "list_versions",
    # runs
    "create_run",
    "mark_run_running",
    "end_run",
    "get_run",
    "list_runs",
    "append_run_log",
    "list_queued_runs",
    "cleanup_stale_runs",
    # schedules
    "create_schedule",
    "get_schedule",
    "list_schedules",
    "update_schedule",
    "delete_schedule",
    "set_schedule_next_fire",
    "mark_schedule_fired",
    "list_due_schedules",
]
