"""Smoke tests for the Worker abstraction. Uses a fake browser_manager so we don't
actually launch chromium."""
import pytest
from backend.worker import LocalWorker, WorkerCapacity, get_default_worker, set_default_worker, Worker

def test_default_worker_is_local():
    w = get_default_worker()
    assert isinstance(w, LocalWorker)
    assert isinstance(w, Worker)

def test_capacity_dataclass():
    c = WorkerCapacity(worker_id="x", region="us", max_profiles=5, running_count=2)
    assert c.available_slots == 3

@pytest.mark.asyncio
async def test_local_worker_status_when_not_running(monkeypatch):
    w = LocalWorker(worker_id="t", region="t")
    # Monkey-patch the running dict on the shared singleton
    from backend import dependencies
    monkeypatch.setattr(dependencies.browser_mgr, "running", {}, raising=False)
    s = await w.status("nonexistent-profile")
    assert s == {"running": False}
    assert await w.is_running("nonexistent-profile") is False
    assert await w.cdp_url("nonexistent-profile") is None

@pytest.mark.asyncio
async def test_capacity_reports_running_count(monkeypatch):
    from backend import dependencies
    monkeypatch.setattr(dependencies.browser_mgr, "running", {"a": object(), "b": object()}, raising=False)
    w = LocalWorker(worker_id="x", region="x", max_profiles=10)
    c = await w.capacity()
    assert c.running_count == 2
    assert c.available_slots == 8

def test_set_default_worker_swaps():
    original = get_default_worker()
    custom = LocalWorker(worker_id="custom", region="custom")
    set_default_worker(custom)
    try:
        assert get_default_worker() is custom
    finally:
        set_default_worker(original)
