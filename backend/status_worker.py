"""Background uptime probe worker.

Every :data:`TICK_INTERVAL_SECONDS` (60 s by default) the worker pings
each entry in :data:`PROBES` over plain HTTP to ``localhost`` and writes
the outcome to ``service_checks`` via :func:`backend.db_status.record_check`.
The aggregated read side lives in :mod:`backend.routers.system`
(``GET /api/status/public``) and renders on the frontend ``/status`` route.

Why a local-loopback probe rather than an external SaaS (UptimeRobot
et al.)?

* Tight integration — the probe ticks under the same Python process
  as everything it monitors, so the latency we record is the *real*
  request-handling latency, not external-network latency.
* No external dependency / cost — self-hosted installs work
  out-of-the-box without standing up a third-party account.
* Simpler RLS story — :func:`backend.middleware_rls.system_context`
  already exists for background workers; reusing it keeps the schema
  out of the multi-tenant RLS regime.

Design contract (mirrors :mod:`backend.proxy_health`):

* **Non-blocking startup** — :func:`start` only schedules the task.
* **Fail-safe** — every probe error is swallowed and recorded as a
  ``down`` row. The outer loop catches unexpected exceptions so one
  bad tick can never kill the worker.
* **Bounded** — concurrency is per-tick (``asyncio.gather`` of the
  small ``PROBES`` list); we never queue ticks if a previous one is
  slow because the loop body is itself sequential.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx

from . import db_status
from .middleware_rls import system_context

logger = logging.getLogger("cloakbrowser.status_worker")


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

TICK_INTERVAL_SECONDS = 60
PROBE_TIMEOUT_SECONDS = 10
# Healthy probes returning >= this many ms are demoted from ``ok`` to
# ``degraded`` — same row gets recorded but the public page colours it
# yellow instead of green. 2 s is generous for a local-loopback probe
# but small enough to catch event-loop starvation early.
DEGRADED_LATENCY_MS = 2000

CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60  # once a day
CLEANUP_RETENTION_DAYS = 30


# Probes run each tick. ``service_name`` is the value persisted in
# ``service_checks.service_name`` (and surfaced verbatim on the public
# status page). Adding a probe is one line — no migration needed.
def _probe_base_url() -> str:
    """Pull the self-probe base URL from the env.

    Defaults to ``http://localhost:8080`` because that is where the
    FastAPI app binds in every deploy template we ship. Tests that
    don't have a live server can override via ``STATUS_PROBE_BASE_URL``
    so the worker's first tick targets their fixture instead.
    """
    return os.environ.get("STATUS_PROBE_BASE_URL", "http://localhost:8080")


PROBES: list[dict[str, str]] = [
    {"service_name": "api", "path": "/api/status"},
    {"service_name": "auth", "path": "/api/auth/status"},
]


# Module-level worker state. ``None`` until :func:`start` is called.
_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None
# Wall-clock of the last successful cleanup; ``0.0`` forces a cleanup
# on the first tick that completes after a restart.
_last_cleanup_at: float = 0.0


# ---------------------------------------------------------------------------
# Probe helpers
# ---------------------------------------------------------------------------


async def _probe_one(client: httpx.AsyncClient, probe: dict[str, str]) -> None:
    """Run one HTTP probe and persist the outcome. Swallows all errors."""
    service = probe["service_name"]
    path = probe["path"]
    url = _probe_base_url().rstrip("/") + path

    started = time.monotonic()
    try:
        resp = await client.get(url, timeout=PROBE_TIMEOUT_SECONDS)
        latency_ms = int((time.monotonic() - started) * 1000)
        if resp.status_code >= 500:
            with system_context():
                db_status.record_check(
                    service,
                    status="down",
                    latency_ms=latency_ms,
                    error_message=f"HTTP {resp.status_code}",
                )
        elif resp.status_code >= 400:
            # 4xx (e.g. unauth) on a probe path is unexpected but not a
            # server-side outage — record as ``degraded`` so it surfaces
            # without flipping the page red.
            with system_context():
                db_status.record_check(
                    service,
                    status="degraded",
                    latency_ms=latency_ms,
                    error_message=f"HTTP {resp.status_code}",
                )
        elif latency_ms >= DEGRADED_LATENCY_MS:
            with system_context():
                db_status.record_check(
                    service,
                    status="degraded",
                    latency_ms=latency_ms,
                    error_message=f"slow: {latency_ms}ms",
                )
        else:
            with system_context():
                db_status.record_check(
                    service, status="ok", latency_ms=latency_ms
                )
    except Exception as exc:  # noqa: BLE001 — record & continue
        err = f"{type(exc).__name__}: {str(exc)[:200]}"
        try:
            with system_context():
                db_status.record_check(
                    service, status="down", latency_ms=None, error_message=err
                )
        except Exception:  # noqa: BLE001
            logger.exception("record_check down-path failed for %s", service)


async def _run_one_pass() -> None:
    """Probe every entry in ``PROBES`` then run cleanup if it is due."""
    global _last_cleanup_at

    async with httpx.AsyncClient(timeout=PROBE_TIMEOUT_SECONDS) as client:
        await asyncio.gather(
            *(_probe_one(client, p) for p in PROBES),
            return_exceptions=True,
        )

    # Periodic GC of old rows. Run *after* probes so a slow cleanup
    # never delays the row insert for "this tick".
    now = time.monotonic()
    if now - _last_cleanup_at >= CLEANUP_INTERVAL_SECONDS:
        try:
            with system_context():
                deleted = db_status.cleanup_old(CLEANUP_RETENTION_DAYS)
            if deleted:
                logger.info("service_checks cleanup removed %s rows", deleted)
            _last_cleanup_at = now
        except Exception:  # noqa: BLE001
            logger.exception("service_checks cleanup failed")


async def _worker_loop(stop: asyncio.Event) -> None:
    """Forever-loop until ``stop`` is set. One tick then sleep, repeat."""
    logger.info(
        "status_worker started (interval=%ss, probes=%s)",
        TICK_INTERVAL_SECONDS,
        [p["service_name"] for p in PROBES],
    )
    while not stop.is_set():
        try:
            await _run_one_pass()
        except Exception:  # noqa: BLE001
            logger.exception("status_worker pass crashed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("status_worker stopped")


# ---------------------------------------------------------------------------
# Public lifecycle
# ---------------------------------------------------------------------------


async def start() -> None:
    """Kick off the background worker. Idempotent."""
    global _worker_task, _stop_event
    if _worker_task is not None and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(
        _worker_loop(_stop_event), name="status_worker"
    )


async def stop() -> None:
    """Signal the worker to stop and wait up to 5 s for it to drain."""
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
            logger.exception("status_worker raised on shutdown")
    _worker_task = None
    _stop_event = None


__all__ = ["start", "stop", "TICK_INTERVAL_SECONDS", "PROBES"]
