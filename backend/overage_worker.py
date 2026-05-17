"""Background worker: flush unreported overage events to Stripe.

Phase 7 phase 2 — the request-path side of overage billing
(:func:`backend.billing.overage.emit_overage`) only writes to Postgres,
because Stripe latency / outages must not affect the user-visible
action. This worker drains the resulting ledger queue every
``OVERAGE_FLUSH_INTERVAL_SECONDS`` (default 60s) by calling
:func:`backend.billing.overage.report_to_stripe` on each
``reported = false`` row and marking it on success.

Design contract — mirrors :mod:`backend.proxy_health`:

* **Non-blocking startup.** :func:`start` only schedules the task; it
  never awaits a first pass. A broken DB / Stripe at boot must not
  prevent the server from coming up.
* **Fail-safe.** Per-event errors are swallowed and logged. The outer
  loop catches & logs unexpected exceptions so a single bad iteration
  can never kill the worker. Failed events stay ``reported = false``
  and are retried on the next tick.
* **Idempotent retries.** ``report_to_stripe`` passes the event id as
  Stripe's idempotency key, so if the previous attempt actually
  succeeded but we crashed before persisting the response, the retry
  returns the same record id instead of double-billing.
* **No work when not configured.** If ``STRIPE_SECRET_KEY`` is unset
  the tick is a quick no-op — useful for self-host installs that
  still want overage events accumulated locally for later reconcile.

Disable entirely with ``OVERAGE_FLUSH_ENABLED=false`` (e.g. in tests
or one-off scripts that don't want a background task chewing on the
shared DB).
"""

from __future__ import annotations

import asyncio
import logging
import os

from .middleware_rls import system_context

logger = logging.getLogger("cloakbrowser.overage_worker")

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

TICK_INTERVAL = int(os.environ.get("OVERAGE_FLUSH_INTERVAL_SECONDS", "60"))
ENABLED = os.environ.get("OVERAGE_FLUSH_ENABLED", "true").lower() != "false"

# Cap the per-tick batch so a backlog spike can't stall other workers
# by holding the DB connection too long. Anything left over rolls into
# the next tick — at 60s/tick this still drains 12k events/minute.
BATCH_LIMIT = 200


# Module-level worker state. ``None`` until :func:`start` is called.
_worker_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


# ---------------------------------------------------------------------------
# Tick
# ---------------------------------------------------------------------------


async def _tick() -> None:
    """One drain pass: list unreported, push each, mark on success.

    Both the DB read and the per-event ack run under
    :func:`system_context` because the worker has no user / tenant —
    without the bypass, restrictive RLS from migration 0012 would
    return zero rows for both the SELECT and the UPDATE.
    """
    # Local imports keep this module importable even when the billing
    # subpackage is being patched in tests.
    from .billing import overage, stripe_adapter

    if not stripe_adapter.is_configured():
        # Self-host / dev mode without Stripe — events accumulate in the
        # local ledger and a future reconcile job can replay them once
        # credentials land. Cheap no-op.
        return

    try:
        with system_context():
            events = overage.list_unreported_events(limit=BATCH_LIMIT)
    except Exception:
        logger.exception("overage_worker: list_unreported_events failed")
        return

    if not events:
        return

    for event in events:
        try:
            # report_to_stripe does its own DB lookup for the
            # subscription's line-item id; run it under system_context
            # so the lookup isn't blocked by RLS.
            with system_context():
                rec_id = overage.report_to_stripe(event)
                if rec_id:
                    overage.mark_reported(
                        event["id"], stripe_usage_record_id=rec_id
                    )
                    logger.info(
                        "overage event %s reported to Stripe as %s",
                        event["id"],
                        rec_id,
                    )
                # else: report_to_stripe already logged the cause —
                # leave reported=false so we retry on the next tick.
        except Exception:
            logger.exception(
                "overage_worker: event %s failed", event.get("id")
            )


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


async def _worker_loop(stop: asyncio.Event) -> None:
    """Forever-loop until ``stop`` is set. One tick then sleep, repeat."""
    logger.info(
        "overage_worker started (interval=%ss, batch=%s)",
        TICK_INTERVAL,
        BATCH_LIMIT,
    )
    while not stop.is_set():
        try:
            await _tick()
        except Exception:
            logger.exception("overage_worker tick crashed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_INTERVAL)
        except asyncio.TimeoutError:
            pass
    logger.info("overage_worker stopped")


# ---------------------------------------------------------------------------
# Public lifecycle
# ---------------------------------------------------------------------------


async def start() -> None:
    """Kick off the background worker. Idempotent — safe to call multiple
    times; subsequent calls while a task is running are no-ops. A no-op
    too when ``OVERAGE_FLUSH_ENABLED=false``."""
    global _worker_task, _stop_event
    if not ENABLED:
        logger.info("overage_worker disabled via OVERAGE_FLUSH_ENABLED=false")
        return
    if _worker_task is not None and not _worker_task.done():
        return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(
        _worker_loop(_stop_event), name="overage_worker"
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
            logger.exception("overage_worker raised on shutdown")
    _worker_task = None
    _stop_event = None


__all__ = ["start", "stop", "TICK_INTERVAL", "BATCH_LIMIT"]
