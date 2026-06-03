"""Background worker: expire trial subscriptions after trial_end."""
import asyncio, logging, os
from .middleware_rls import system_context

logger = logging.getLogger(__name__)
TICK_INTERVAL = int(os.environ.get("TRIAL_EXPIRY_TICK_SECONDS", "3600"))  # 1h
ENABLED = os.environ.get("TRIAL_EXPIRY_ENABLED", "true").lower() != "false"

_worker_task = None
_stop_event = None

async def _tick():
    from . import db_billing
    try:
        with system_context():
            count = db_billing.expire_due_trials()
            if count > 0:
                logger.info("trial_expiry: expired %d trials", count)
    except Exception:
        logger.exception("trial_expiry tick failed")

async def _loop(stop):
    logger.info("trial_expiry worker started, interval=%ss", TICK_INTERVAL)
    while not stop.is_set():
        try:
            await _tick()
        except Exception:
            logger.exception("trial_expiry crashed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_INTERVAL)
        except asyncio.TimeoutError:
            pass

async def start():
    global _worker_task, _stop_event
    if not ENABLED: return
    if _worker_task and not _worker_task.done(): return
    _stop_event = asyncio.Event()
    _worker_task = asyncio.create_task(_loop(_stop_event))

async def stop():
    global _worker_task, _stop_event
    if _stop_event: _stop_event.set()
    if _worker_task:
        try: await asyncio.wait_for(_worker_task, timeout=5)
        except asyncio.TimeoutError: _worker_task.cancel()
