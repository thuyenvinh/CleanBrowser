"""Background task: stop browser sessions running longer than IDLE_TIMEOUT.

Phase 3 phase 1 (ARCHITECTURE §2.4): hard time-limit. Any active
``profile_sessions`` row whose ``started_at`` is older than ``IDLE_TIMEOUT``
seconds is stopped — regardless of actual VNC/CDP activity. The user
re-launches manually via the UI.

A future phase will track ``last_activity_at`` via VNC/CDP middleware and
reap based on real idleness instead of wall-clock age.

Lifecycle mirrors :mod:`backend.proxy_health`: a single ``asyncio.Task``
started/stopped from the FastAPI lifespan.
"""

from __future__ import annotations

import asyncio
import logging
import os

from backend import database as db
from backend.middleware_rls import system_context

logger = logging.getLogger(__name__)

TICK_INTERVAL = int(os.environ.get("IDLE_REAPER_TICK_SECONDS", "300"))      # 5 min
IDLE_TIMEOUT = int(os.environ.get("IDLE_REAPER_TIMEOUT_SECONDS", "1800"))   # 30 min
ENABLED = os.environ.get("IDLE_REAPER_ENABLED", "true").lower() == "true"

_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


async def _reap_one(session: dict) -> None:
    profile_id = session["profile_id"]
    try:
        from backend.browser_manager import browser_mgr
        if profile_id not in browser_mgr.running:
            # Session DB record but no in-process state — already orphaned. End session.
            with system_context():
                db.end_session(
                    session["id"],
                    status="crashed",
                    error_message="reaped: orphan session",
                )
            logger.info("idle_reaper: cleaned orphan session %s", session["id"])
            return
        logger.info(
            "idle_reaper: stopping profile %s (session %s) after %ss",
            profile_id, session["id"], IDLE_TIMEOUT,
        )
        await browser_mgr.stop_profile(profile_id)
    except Exception:
        logger.exception("idle_reaper: failed to stop %s", profile_id)


async def _tick() -> None:
    try:
        with system_context():
            sessions = db.list_long_running_sessions(min_age_seconds=IDLE_TIMEOUT)
    except Exception:
        logger.exception("idle_reaper: list failed")
        return
    for s in sessions:
        await _reap_one(s)


async def _worker_loop(stop: asyncio.Event) -> None:
    logger.info(
        "idle_reaper started: timeout=%ss tick=%ss", IDLE_TIMEOUT, TICK_INTERVAL
    )
    while not stop.is_set():
        try:
            await _tick()
        except Exception:
            logger.exception("idle_reaper tick crashed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_INTERVAL)
        except asyncio.TimeoutError:
            pass
    logger.info("idle_reaper stopping")


async def start() -> None:
    global _worker_task, _stop_event
    if not ENABLED:
        logger.info("idle_reaper disabled by env")
        return
    if _worker_task and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(_worker_loop(_stop_event), name="idle_reaper")


async def stop() -> None:
    global _worker_task, _stop_event
    if _stop_event:
        _stop_event.set()
    if _worker_task:
        try:
            await asyncio.wait_for(_worker_task, timeout=5)
        except asyncio.TimeoutError:
            _worker_task.cancel()
            try:
                await _worker_task
            except (asyncio.CancelledError, Exception):
                pass
        except Exception:
            logger.exception("idle_reaper worker raised on shutdown")
    _worker_task = None
    _stop_event = None


__all__ = ["start", "stop", "TICK_INTERVAL", "IDLE_TIMEOUT"]
