"""Tests for the H1 fix in :func:`backend.automation_scheduler._fire_schedule`.

Before the fix, a cron schedule pinned to a profile would fire every minute
the cron matched even if the profile wasn't running — spawning a run that
immediately failed with "profile not running", polluting the run history,
and burning the user's automation_minutes quota for nothing.

The fix: when ``schedule.profile_id`` is set, verify
``profile_id in browser_mgr.running`` BEFORE creating the run row.
Schedule fires with NULL profile_id are unaffected (script automations
don't need a live profile).
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from backend import automation_scheduler, db_auth, db_automation


def _make_workspace_and_automation(tmp_db) -> tuple[str, dict, dict]:
    """Sign up a tenant, create an automation, attach an initial version.

    Returns ``(workspace_id, automation, version)``. The version is needed
    so ``_fire_schedule`` can resolve ``latest_version_id`` → version row.
    """
    _, user, ws = db_auth.signup(
        email=f"sched+{uuid.uuid4().hex[:8]}@example.test",
        password="password123",
    )
    auto = db_automation.create_automation(
        workspace_id=ws["id"],
        name="sched-test",
        kind="flow",
    )
    version = db_automation.create_version(
        automation_id=auto["id"],
        kind="flow",
        dsl_json={"version": 1, "start": "n1", "nodes": []},
        created_by_user_id=user["id"],
    )
    return ws["id"], db_automation.get_automation(auto["id"]), version


def _count_runs(automation_version_id: str) -> int:
    """Helper: count automation_runs rows for a given version id.

    Tests assert against this delta to confirm whether ``_fire_schedule``
    actually inserted a queued run or short-circuited.
    """
    from backend.database import get_db

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM automation_runs "
                "WHERE automation_version_id = %s",
                (automation_version_id,),
            )
            (n,) = cur.fetchone()
    return n


@pytest.fixture()
def _no_executor(monkeypatch):
    """Replace ``asyncio.create_task`` inside the scheduler module with a
    no-op so the fire path doesn't try to spin up the real (Playwright-
    dependent) executor task. We only care that ``create_run`` ran."""
    import asyncio

    monkeypatch.setattr(
        automation_scheduler.asyncio,
        "create_task",
        lambda coro, name=None: (coro.close() or None),
    )


@pytest.mark.asyncio
async def test_fire_schedule_without_profile_id_fires(tmp_db, _no_executor):
    """``profile_id=None`` skips the H1 check and always fires."""
    _, auto, version = _make_workspace_and_automation(tmp_db)
    before = _count_runs(version["id"])
    schedule = {
        "id": str(uuid.uuid4()),
        "automation_id": auto["id"],
        "profile_id": None,
    }
    await automation_scheduler._fire_schedule(schedule)
    after = _count_runs(version["id"])
    assert after == before + 1


def _make_profile(workspace_id: str) -> str:
    """Create a real profile row so the automation_runs FK doesn't trip.

    The scheduler's H1 check is purely against ``browser_mgr.running``
    (a dict), but the run-row insert downstream still requires the
    profile_id to exist in ``profiles`` — otherwise we can't tell the
    difference between "skipped by H1" and "skipped by FK violation".
    """
    from backend import database as db

    profile = db.create_profile(name=f"sched-prof-{uuid.uuid4().hex[:6]}", workspace_id=workspace_id)
    return profile["id"]


@pytest.mark.asyncio
async def test_fire_schedule_with_running_profile_fires(
    tmp_db, _no_executor, monkeypatch
):
    """profile_id present + in browser_mgr.running → run row created."""
    ws_id, auto, version = _make_workspace_and_automation(tmp_db)
    profile_id = _make_profile(ws_id)
    # Patch the dependency the scheduler imports lazily.
    from backend import dependencies

    monkeypatch.setattr(
        dependencies.browser_mgr, "running", {profile_id: object()}, raising=False
    )

    before = _count_runs(version["id"])
    schedule = {
        "id": str(uuid.uuid4()),
        "automation_id": auto["id"],
        "profile_id": profile_id,
    }
    await automation_scheduler._fire_schedule(schedule)
    after = _count_runs(version["id"])
    assert after == before + 1


@pytest.mark.asyncio
async def test_fire_schedule_with_missing_profile_skips(
    tmp_db, _no_executor, monkeypatch
):
    """profile_id present + NOT in browser_mgr.running → fire is skipped."""
    ws_id, auto, version = _make_workspace_and_automation(tmp_db)
    profile_id = _make_profile(ws_id)
    from backend import dependencies

    # browser_mgr.running is empty → the profile_id won't be found.
    monkeypatch.setattr(dependencies.browser_mgr, "running", {}, raising=False)

    before = _count_runs(version["id"])
    schedule = {
        "id": str(uuid.uuid4()),
        "automation_id": auto["id"],
        "profile_id": profile_id,
    }
    await automation_scheduler._fire_schedule(schedule)
    after = _count_runs(version["id"])
    # H1: no run was created.
    assert after == before


@pytest.mark.asyncio
async def test_fire_schedule_count_matches_running_set(
    tmp_db, _no_executor, monkeypatch
):
    """Fire two schedules: one with a live profile, one without. Exactly
    one run should be created — the running-set membership decides which."""
    ws_id, auto, version = _make_workspace_and_automation(tmp_db)
    live_id = _make_profile(ws_id)
    dead_id = _make_profile(ws_id)
    from backend import dependencies

    monkeypatch.setattr(
        dependencies.browser_mgr, "running", {live_id: object()}, raising=False
    )

    before = _count_runs(version["id"])
    await automation_scheduler._fire_schedule(
        {
            "id": str(uuid.uuid4()),
            "automation_id": auto["id"],
            "profile_id": live_id,
        }
    )
    await automation_scheduler._fire_schedule(
        {
            "id": str(uuid.uuid4()),
            "automation_id": auto["id"],
            "profile_id": dead_id,
        }
    )
    after = _count_runs(version["id"])
    assert after - before == 1
