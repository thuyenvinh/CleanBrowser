"""Tests for automation run cancellation surface (router + _RUN_TASKS).

The router file owns a module-level ``_RUN_TASKS`` registry — runs in
flight register themselves so ``POST /runs/{id}/cancel`` can ``Task.cancel``
them. We test:

* The cancel endpoint flips a queued run's status to 'cancelled'.
* Cancelling a run already in a terminal state returns 409.
* Viewers (role floor: launcher) get 403.
* ``_RUN_TASKS`` is cleaned up by the execute path's ``finally`` clause.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest

from backend import db_auth, db_automation
from backend.routers import automations as auto_router


def _make_user_and_automation(tmp_db) -> tuple[dict, dict, dict]:
    """Create a user with a tenant, a workspace, an automation + version.

    Returns ``(user, automation, version)``. The user owns the workspace
    (role=owner) so role-gated assertions can promote/demote them via a
    second peer.
    """
    _, user, ws = db_auth.signup(
        email=f"runc+{uuid.uuid4().hex[:8]}@example.test",
        password="password123",
    )
    user["workspace_id"] = ws["id"]
    user["tenant_id"] = ws["tenant_id"]
    auto = db_automation.create_automation(
        workspace_id=ws["id"], name="run-cancel", kind="flow"
    )
    version = db_automation.create_version(
        automation_id=auto["id"],
        kind="flow",
        dsl_json={"version": 1, "start": "n1", "nodes": []},
        created_by_user_id=user["id"],
    )
    return user, db_automation.get_automation(auto["id"]), version


def test_cancel_queued_run_flips_status(tmp_db):
    """POST /runs/{id}/cancel on a queued run → status='cancelled'."""
    user, _, version = _make_user_and_automation(tmp_db)
    run = db_automation.create_run(
        automation_version_id=version["id"], triggered_by="manual"
    )
    auto_router.cancel_run(run_id=run["id"], user=user)
    refreshed = db_automation.get_run(run["id"])
    assert refreshed["status"] == "cancelled"


def test_cancel_already_terminal_run_returns_409(tmp_db):
    """Cancelling a 'success' run yields 409."""
    from fastapi import HTTPException

    user, _, version = _make_user_and_automation(tmp_db)
    run = db_automation.create_run(
        automation_version_id=version["id"], triggered_by="manual"
    )
    db_automation.mark_run_running(run["id"])
    db_automation.end_run(run["id"], "success")

    with pytest.raises(HTTPException) as excinfo:
        auto_router.cancel_run(run_id=run["id"], user=user)
    assert excinfo.value.status_code == 409


def test_cancel_run_requires_launcher_role(tmp_db):
    """A viewer-only peer cannot cancel — 403 on the role floor."""
    from fastapi import HTTPException

    user, automation, version = _make_user_and_automation(tmp_db)
    # Create a second user, add them to the workspace as 'viewer'.
    _, viewer, _ = db_auth.signup(
        email=f"viewer+{uuid.uuid4().hex[:8]}@example.test",
        password="password123",
    )
    db_auth.add_workspace_member(
        automation["workspace_id"], viewer["id"], "viewer"
    )

    run = db_automation.create_run(
        automation_version_id=version["id"], triggered_by="manual"
    )

    with pytest.raises(HTTPException) as excinfo:
        auto_router.cancel_run(run_id=run["id"], user=viewer)
    assert excinfo.value.status_code == 403


def test_cancel_unknown_run_returns_404(tmp_db):
    """Unknown run id → 404 'Run not found'."""
    from fastapi import HTTPException

    user, _, _ = _make_user_and_automation(tmp_db)
    bogus = str(uuid.uuid4())
    with pytest.raises(HTTPException) as excinfo:
        auto_router.cancel_run(run_id=bogus, user=user)
    assert excinfo.value.status_code == 404


def test_run_tasks_cleared_after_execute_finally(tmp_db, monkeypatch):
    """_execute_run_async registers in _RUN_TASKS on entry and pop()s in
    its ``finally`` clause regardless of how it exits. Drive a minimal
    failure path (no profile → end_run("failure")) and assert the slot
    is empty afterwards."""
    user, automation, version = _make_user_and_automation(tmp_db)
    run = db_automation.create_run(
        automation_version_id=version["id"], triggered_by="manual"
    )

    # Make sure the registry is empty before; the asyncio.run() call below
    # populates and then must clear it.
    auto_router._RUN_TASKS.pop(run["id"], None)

    # Run without a profile_id → executor hits the early "profile_id
    # required" path and writes a failure end_run, then falls through
    # the finally that pops _RUN_TASKS.
    asyncio.run(
        auto_router._execute_run_async(
            run_id=run["id"],
            version={
                "kind": "flow",
                "dsl_json": {"version": 1, "start": "n1", "nodes": []},
            },
            profile_id=None,
        )
    )
    assert run["id"] not in auto_router._RUN_TASKS
    refreshed = db_automation.get_run(run["id"])
    assert refreshed["status"] in ("failure", "cancelled")
