"""Worker abstraction. Phase 3 phase 1: LocalWorker wraps in-process browser_manager.
Future phases: RemoteWorker over gRPC/NATS to a separate pod."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
import asyncio
import logging

logger = logging.getLogger(__name__)


@dataclass
class WorkerCapacity:
    worker_id: str
    region: str
    max_profiles: int
    running_count: int
    cpu_percent: float | None = None
    ram_mb_used: int | None = None

    @property
    def available_slots(self) -> int:
        return max(0, self.max_profiles - self.running_count)


@dataclass
class LaunchResult:
    session_id: str
    worker_id: str
    cdp_port: int
    vnc_port: int
    display_num: int


@runtime_checkable
class Worker(Protocol):
    worker_id: str
    region: str

    async def launch(self, profile_id: str) -> LaunchResult: ...
    async def stop(self, profile_id: str) -> None: ...
    async def status(self, profile_id: str) -> dict: ...
    async def capacity(self) -> WorkerCapacity: ...
    async def is_running(self, profile_id: str) -> bool: ...
    async def cdp_url(self, profile_id: str) -> str | None: ...


class LocalWorker:
    """In-process worker that delegates to ``browser_manager.browser_mgr``.
    This is the only Worker impl in Phase 3 phase 1; remote worker comes later."""

    def __init__(self, worker_id: str = "local-0", region: str = "local",
                 max_profiles: int = 10):
        self.worker_id = worker_id
        self.region = region
        self.max_profiles = max_profiles

    def _mgr(self):
        # Lazy import to avoid circular at module load. The shared singleton
        # lives in backend.dependencies (created once at app boot).
        from backend.dependencies import browser_mgr
        return browser_mgr

    async def launch(self, profile_id: str) -> LaunchResult:
        from backend import database as db
        mgr = self._mgr()
        profile = db.get_profile(profile_id)
        if not profile:
            raise RuntimeError(f"profile {profile_id} not found")
        # browser_manager.launch already handles session creation, port alloc, etc.
        await mgr.launch(profile)
        rp = mgr.running.get(profile_id)
        if not rp:
            raise RuntimeError(f"launch failed for {profile_id}")
        return LaunchResult(
            session_id=rp.session_id or "",
            worker_id=self.worker_id,
            cdp_port=rp.cdp_port,
            vnc_port=rp.ws_port,
            display_num=rp.display,
        )

    async def stop(self, profile_id: str) -> None:
        await self._mgr().stop(profile_id)

    async def status(self, profile_id: str) -> dict:
        rp = self._mgr().running.get(profile_id)
        if not rp:
            return {"running": False}
        return {
            "running": True,
            "session_id": rp.session_id,
            "worker_id": self.worker_id,
            "cdp_port": rp.cdp_port,
            "vnc_port": rp.ws_port,
        }

    async def is_running(self, profile_id: str) -> bool:
        return profile_id in self._mgr().running

    async def cdp_url(self, profile_id: str) -> str | None:
        rp = self._mgr().running.get(profile_id)
        if not rp:
            return None
        return f"http://localhost:{rp.cdp_port}"

    async def capacity(self) -> WorkerCapacity:
        return WorkerCapacity(
            worker_id=self.worker_id, region=self.region,
            max_profiles=self.max_profiles,
            running_count=len(self._mgr().running),
        )


# Module-level default worker for current single-node deployment.
# Future: WorkerPool selects from registered Worker instances.
_default: Worker | None = None

def get_default_worker() -> Worker:
    global _default
    if _default is None:
        _default = LocalWorker()
    return _default

def set_default_worker(worker: Worker) -> None:
    """For tests / future remote-worker bootstrap."""
    global _default
    _default = worker
