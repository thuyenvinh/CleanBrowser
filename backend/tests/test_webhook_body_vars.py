"""Tests for ``set_run_initial_vars`` — webhook body → run vars hand-off (H5).

The webhook endpoint pipes its JSON body into the freshly queued run via
``set_run_initial_vars`` so the executor can read it from ``result_json``
under the ``__initial_vars__`` marker.
"""
from __future__ import annotations

import uuid

from backend import db_auth, db_automation


def _make_run(tmp_db) -> str:
    """Helper: create user + automation + version + queued run, return run id."""
    _, user, ws = db_auth.signup(
        email=f"webhook+{uuid.uuid4().hex[:8]}@example.test",
        password="some-secure-password",
    )
    automation = db_automation.create_automation(
        workspace_id=ws["id"], name="webhook-test", kind="flow"
    )
    version = db_automation.create_version(
        automation_id=automation["id"], kind="flow", dsl_json={"steps": []}
    )
    run = db_automation.create_run(
        automation_version_id=version["id"], triggered_by="webhook"
    )
    return run["id"]


def test_set_run_initial_vars_writes_marker(tmp_db):
    """A non-empty dict lands under the ``__initial_vars__`` marker."""
    run_id = _make_run(tmp_db)
    db_automation.set_run_initial_vars(run_id, {"foo": "bar", "n": 42})

    run = db_automation.get_run(run_id)
    assert run is not None
    assert run["result_json"] == {"__initial_vars__": {"foo": "bar", "n": 42}}


def test_set_run_initial_vars_empty_dict_still_writes_marker(tmp_db):
    """Empty payload still produces a ``{"__initial_vars__": {}}`` envelope.

    Important: the executor distinguishes "webhook fired with no body" from
    "no webhook" by the *presence* of the marker, not its contents.
    """
    run_id = _make_run(tmp_db)
    db_automation.set_run_initial_vars(run_id, {})

    run = db_automation.get_run(run_id)
    assert run is not None
    assert run["result_json"] == {"__initial_vars__": {}}


def test_get_run_returns_full_result_json(tmp_db):
    """``get_run`` round-trips ``result_json`` faithfully (no key loss)."""
    run_id = _make_run(tmp_db)
    payload = {"a": 1, "nested": {"b": [1, 2, 3]}, "flag": True}
    db_automation.set_run_initial_vars(run_id, payload)

    run = db_automation.get_run(run_id)
    assert run["result_json"] == {"__initial_vars__": payload}


def test_set_run_initial_vars_override_last_wins(tmp_db):
    """Two consecutive calls — the second payload replaces the first."""
    run_id = _make_run(tmp_db)
    db_automation.set_run_initial_vars(run_id, {"first": True})
    db_automation.set_run_initial_vars(run_id, {"second": True})

    run = db_automation.get_run(run_id)
    assert run["result_json"] == {"__initial_vars__": {"second": True}}
