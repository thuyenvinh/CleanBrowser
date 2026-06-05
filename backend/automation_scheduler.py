"""Background automation scheduler worker.

Ticks once a minute and fires any :class:`automation_schedules` whose
``next_fire_at`` has elapsed. For each due schedule:

1. Resolve the parent automation's ``latest_version_id``.
2. Create a new ``automation_runs`` row via
   :func:`backend.db_automation.create_run` (``triggered_by='schedule'``).
3. Schedule a fire-and-forget executor task using
   :func:`backend.routers.automations._execute_run_async`.
4. Persist ``last_fire_at`` (now) and the next cron occurrence into
   ``next_fire_at`` so the row is ready for its next tick.

The worker is a single ``asyncio.Task`` driven by the FastAPI lifespan in
:mod:`backend.main`, mirroring :mod:`backend.proxy_health`:

* **Non-blocking startup.** :func:`start` only schedules the task; bootstrap
  work (initialising NULL ``next_fire_at`` on enabled schedules) happens
  *inside* the worker so a slow DB at boot can't block uvicorn.
* **Fail-safe.** Every per-schedule operation is wrapped — a single bad
  cron expression or executor crash can never kill the loop.
* **Lazy import.** ``_execute_run_async`` is imported on first fire to
  avoid a router ↔ scheduler circular dependency at module load.

See ARCHITECTURE §2.6 (Phase 4 Task II).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone as tz
from typing import Any

from croniter import croniter

from . import db_automation
from .middleware_rls import system_context

logger = logging.getLogger("cloakbrowser.automation_scheduler")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

TICK_INTERVAL = 60  # seconds between reconcile passes


# Module-level worker state. ``None`` until :func:`start` is called.
_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


# ---------------------------------------------------------------------------
# Cron helpers
# ---------------------------------------------------------------------------


def _compute_next_fire(
    cron_expr: str, tz_name: str, base: datetime
) -> datetime:
    """Return the next ``datetime`` after ``base`` matching ``cron_expr`` in
    ``tz_name``, expressed as a timezone-aware UTC datetime.

    ``base`` should be UTC-aware; we convert into the schedule's local zone
    before iterating so cron semantics ("at 3am") match operator intent,
    then convert the result back to UTC for storage. An unknown zone falls
    back to UTC so a typo can't take the worker out.
    """
    import zoneinfo

    try:
        zone = zoneinfo.ZoneInfo(tz_name)
    except Exception:  # noqa: BLE001 — unknown zone, fall back to UTC
        logger.warning("unknown timezone %r, falling back to UTC", tz_name)
        zone = tz.utc  # type: ignore[assignment]

    base_local = base.astimezone(zone)
    it = croniter(cron_expr, base_local)
    next_local = it.get_next(datetime)
    # croniter preserves tzinfo from ``base_local``; normalise to UTC.
    return next_local.astimezone(tz.utc)


# ---------------------------------------------------------------------------
# Fire helpers
# ---------------------------------------------------------------------------


async def _fire_schedule(schedule: dict[str, Any]) -> None:
    """Create a run for ``schedule`` and dispatch the executor.

    Errors are swallowed — the outer tick loop logs the schedule id so a
    single bad row can't stop reconcile of the rest of the batch.
    """
    schedule_id = schedule["id"]
    try:
        # All DB reads/writes in this fire path run under ``system_context``
        # because the scheduler is a cron-driven worker with no user / tenant
        # binding — without the bypass, the restrictive RLS policies from
        # migration 0012 would hide the automation row and the run insert
        # would silently see zero affected rows.
        with system_context():
            auto = db_automation.get_automation(schedule["automation_id"])
            if not auto or not auto.get("latest_version_id"):
                logger.warning(
                    "schedule %s: automation has no version, skipping",
                    schedule_id,
                )
                return

            version = db_automation.get_version(auto["latest_version_id"])
            if version is None:
                logger.warning(
                    "schedule %s: latest_version_id points at missing row",
                    schedule_id,
                )
                return

            # H1: if the schedule is pinned to a profile, verify the profile
            # is actually running BEFORE creating a run row. Otherwise we'd
            # spam ``failure`` rows ("profile not running") every minute the
            # cron matches, polluting the run history and burning quota for
            # nothing. Skip silently — the next cron occurrence will retry.
            profile_id = schedule.get("profile_id")
            if profile_id:
                from .dependencies import browser_mgr  # noqa: WPS433

                if profile_id not in browser_mgr.running:
                    logger.info(
                        "schedule %s: profile %s not running — skipping fire",
                        schedule_id,
                        profile_id,
                    )
                    return

            run = db_automation.create_run(
                automation_version_id=auto["latest_version_id"],
                profile_id=schedule.get("profile_id"),
                triggered_by="schedule",
            )

        # Lazy import: routers/automations imports plenty of heavy modules
        # (playwright, etc.); deferring it until first fire keeps the
        # scheduler cheap to import at app boot.
        from .routers.automations import _execute_run_async

        asyncio.create_task(
            _execute_run_async(run["id"], version, schedule.get("profile_id")),
            name=f"automation_run:{run['id']}",
        )
        logger.info(
            "schedule %s fired run %s (automation=%s)",
            schedule_id,
            run["id"],
            schedule["automation_id"],
        )
    except Exception:  # noqa: BLE001
        logger.exception("schedule %s: fire failed", schedule_id)


async def _tick() -> None:
    """Run one reconcile pass: pick up due schedules and fire each."""
    now = datetime.now(tz.utc)
    try:
        with system_context():
            due = db_automation.list_due_schedules(now)
    except Exception:
        logger.exception("scheduler tick: list_due_schedules failed")
        return

    for s in due:
        try:
            await _fire_schedule(s)
            # Record the fire BEFORE computing next, so a bad cron expr
            # at least bumps last_fire_at (loop won't pick the row again
            # in this tick since next_fire_at is being updated below).
            with system_context():
                db_automation.mark_schedule_fired(s["id"], now)
            try:
                next_fire = _compute_next_fire(s["cron"], s["timezone"], now)
                with system_context():
                    db_automation.set_schedule_next_fire(s["id"], next_fire)
            except Exception:
                logger.exception(
                    "schedule %s: failed to compute/persist next_fire",
                    s["id"],
                )
        except Exception:
            logger.exception(
                "schedule %s: failed to fire/reschedule", s["id"]
            )


async def _init_next_fire_for_new_schedules() -> None:
    """One-shot startup pass: any enabled schedule still missing
    ``next_fire_at`` (i.e. just-created via the API and never reconciled)
    gets it computed once so the next tick can pick it up."""
    try:
        with system_context():
            all_schedules = db_automation.list_schedules(due_only=False)
    except Exception:
        logger.exception("scheduler init: list_schedules failed")
        return

    now = datetime.now(tz.utc)
    for s in all_schedules:
        if not s.get("enabled") or s.get("next_fire_at") is not None:
            continue
        try:
            next_fire = _compute_next_fire(s["cron"], s["timezone"], now)
            with system_context():
                db_automation.set_schedule_next_fire(s["id"], next_fire)
            logger.info(
                "schedule %s initialised next_fire_at=%s",
                s["id"],
                next_fire.isoformat(),
            )
        except Exception:
            logger.exception(
                "schedule %s: init next_fire failed", s["id"]
            )


async def _worker_loop(stop: asyncio.Event) -> None:
    """Forever-loop until ``stop`` is set. Each iteration runs one tick
    then sleeps ``TICK_INTERVAL`` (or wakes early on stop)."""
    logger.info(
        "automation_scheduler worker started (interval=%ss)", TICK_INTERVAL
    )

    # Bootstrap inside the worker so a slow DB at boot can't block startup.
    try:
        await _init_next_fire_for_new_schedules()
    except Exception:
        logger.exception("scheduler init phase failed")

    while not stop.is_set():
        try:
            await _tick()
        except Exception:
            logger.exception("scheduler tick crashed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_INTERVAL)
        except asyncio.TimeoutError:
            pass

    logger.info("automation_scheduler worker stopped")


# ---------------------------------------------------------------------------
# Public lifecycle
# ---------------------------------------------------------------------------


async def start() -> None:
    """Kick off the background worker. Idempotent — safe to call multiple
    times; subsequent calls while a task is running are no-ops."""
    global _worker_task, _stop_event
    if _worker_task is not None and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(
        _worker_loop(_stop_event), name="automation_scheduler_worker"
    )


async def stop() -> None:
    """Signal the worker to stop and wait up to 5 s for it to drain. If the
    task doesn't honor the signal in time it is cancelled."""
    global _worker_task, _stop_event
    if _stop_event is not None:
        _stop_event.set()
    if _worker_task is not None:
        try:
            await asyncio.wait_for(_worker_task, timeout=5)
        except asyncio.TimeoutError:
            _worker_task.cancel()
            try:
                await _worker_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            logger.exception("automation_scheduler worker raised on shutdown")
    _worker_task = None
    _stop_event = None


__all__ = ["start", "stop", "TICK_INTERVAL"]
