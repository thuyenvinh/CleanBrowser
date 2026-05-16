"""Background proxy health-check worker.

Periodically probes every proxy in the pool (by default every 5 minutes)
through ``https://api.ipify.org`` and records the outcome via
:func:`backend.db_proxy.update_proxy_health`. The worker is a single
``asyncio.Task`` started/stopped from the FastAPI lifespan in
:mod:`backend.main`.

Design contract:

* **Non-blocking startup.** :func:`start` only schedules the task; it never
  awaits a first pass. A broken DB or network at boot must not prevent the
  server from coming up.
* **Fail-safe.** Any per-proxy probe error is swallowed and recorded as a
  ``fail`` row. The outer loop catches & logs unexpected exceptions so a
  single bad iteration can never kill the worker.
* **Bounded concurrency.** At most ``CONCURRENT_CHECKS`` probes run in
  parallel via a semaphore — protects upstream APIs and our event loop.

See ARCHITECTURE §2.5.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from . import db_proxy

logger = logging.getLogger("cloakbrowser.proxy_health")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

CHECK_INTERVAL_SECONDS = 300  # 5 minutes
PROXY_TIMEOUT_SECONDS = 10
CONCURRENT_CHECKS = 10
PROBE_URL = "https://api.ipify.org?format=json"


# Module-level worker state. ``None`` until :func:`start` is called.
_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


# ---------------------------------------------------------------------------
# Probe helpers
# ---------------------------------------------------------------------------


async def _check_one(proxy_row: dict[str, Any]) -> None:
    """Probe a single proxy and record the outcome. Swallows all errors."""
    proxy_id = proxy_row["id"]

    # Resolve plaintext URL (Fernet-decrypt happens inside build_proxy_url).
    try:
        url = db_proxy.build_proxy_url(proxy_id)
    except Exception as exc:  # noqa: BLE001 — record & continue
        try:
            db_proxy.update_proxy_health(
                proxy_id,
                status="fail",
                last_error=f"build_url_failed: {type(exc).__name__}: {str(exc)[:180]}",
            )
        except Exception:  # noqa: BLE001
            logger.exception("update_proxy_health failed for %s", proxy_id)
        return

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(
            proxy=url, timeout=PROXY_TIMEOUT_SECONDS
        ) as client:
            resp = await client.get(PROBE_URL)
            resp.raise_for_status()
        latency_ms = int((time.monotonic() - started) * 1000)

        # Optional country detection — mirrors the pattern used by the
        # synchronous /api/proxies/{id}/test endpoint.
        country_code: str | None = None
        try:
            from . import geoip  # type: ignore[attr-defined]

            lookup = getattr(geoip, "country_for_response", None)
            if callable(lookup):
                country_code = lookup(resp)
        except ImportError:
            country_code = None
        except Exception:  # noqa: BLE001
            logger.exception("geoip lookup failed for proxy %s", proxy_id)
            country_code = None

        try:
            db_proxy.update_proxy_health(
                proxy_id,
                status="ok",
                latency_ms=latency_ms,
                last_error=None,
                country_code=country_code,
            )
        except Exception:  # noqa: BLE001
            logger.exception("update_proxy_health ok-path failed for %s", proxy_id)
    except Exception as exc:  # noqa: BLE001 — record & continue
        err = f"{type(exc).__name__}: {str(exc)[:200]}"
        try:
            db_proxy.update_proxy_health(
                proxy_id, status="fail", last_error=err
            )
        except Exception:  # noqa: BLE001
            logger.exception("update_proxy_health fail-path failed for %s", proxy_id)


async def _run_one_pass() -> None:
    """Fetch the due-for-check batch and probe each with bounded concurrency."""
    try:
        rows = db_proxy.list_proxies_for_check(stale_minutes=5)
    except Exception:
        logger.exception("failed to list proxies for check")
        return
    if not rows:
        return

    sem = asyncio.Semaphore(CONCURRENT_CHECKS)

    async def _bounded(row: dict[str, Any]) -> None:
        async with sem:
            await _check_one(row)

    await asyncio.gather(
        *(_bounded(r) for r in rows), return_exceptions=True
    )


async def _worker_loop(stop: asyncio.Event) -> None:
    """Forever-loop until ``stop`` is set. Each iteration runs one pass then
    sleeps ``CHECK_INTERVAL_SECONDS`` (or wakes early on stop)."""
    logger.info(
        "proxy_health worker started (interval=%ss, concurrency=%s)",
        CHECK_INTERVAL_SECONDS,
        CONCURRENT_CHECKS,
    )
    while not stop.is_set():
        try:
            await _run_one_pass()
        except Exception:
            logger.exception("proxy_health pass crashed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=CHECK_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
    logger.info("proxy_health worker stopped")


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
        _worker_loop(_stop_event), name="proxy_health_worker"
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
            logger.exception("proxy_health worker raised on shutdown")
    _worker_task = None
    _stop_event = None


__all__ = ["start", "stop", "CHECK_INTERVAL_SECONDS"]
