"""Tests for marketplace admin moderation (M10).

Covers the submit → pending → approve / reject lifecycle on
``marketplace_apps``. Submissions start invisible; approval flips them
public + approved, rejection keeps them invisible + rejected.
"""
from __future__ import annotations

import uuid

from backend import db_auth, db_marketplace


def _submit(slug_suffix: str | None = None) -> dict:
    """Sign up a creator + submit one pending app, return the row.

    Uses a fresh uuid for both the email *and* the slug so reruns against
    a non-truncated ``users`` / ``marketplace_apps`` table never collide.
    """
    label = slug_suffix or "any"
    nonce = uuid.uuid4().hex[:8]
    _, user, _ws = db_auth.signup(
        email=f"mod+{label}+{nonce}@example.test",
        password="some-secure-password",
    )
    return db_marketplace.submit_app(
        slug=f"submit-{label}-{nonce}",
        name=f"Submission {label}",
        description=None,
        kind="flow",
        dsl_json={"steps": []},
        script_language=None,
        script_code=None,
        creator_name="creator",
        creator_url=None,
        submitted_by_user_id=user["id"],
    )


def test_submit_app_starts_pending_and_private(tmp_db):
    """Fresh submissions are ``moderation_status='pending'`` + ``is_public=False``."""
    app = _submit()
    assert app["moderation_status"] == "pending"
    assert app["is_public"] is False
    assert app["is_official"] is False


def test_approve_app_publishes(tmp_db):
    """``approve_app`` flips to ``approved`` + ``is_public=True``."""
    app = _submit()
    updated = db_marketplace.approve_app(app["id"], moderation_notes="ok")
    assert updated is not None
    assert updated["moderation_status"] == "approved"
    assert updated["is_public"] is True
    assert updated["moderation_notes"] == "ok"


def test_reject_app_keeps_private(tmp_db):
    """``reject_app`` flips to ``rejected`` but stays invisible to the public listing."""
    app = _submit()
    updated = db_marketplace.reject_app(app["id"], moderation_notes="too spammy")
    assert updated is not None
    assert updated["moderation_status"] == "rejected"
    assert updated["is_public"] is False
    assert updated["moderation_notes"] == "too spammy"


def test_list_pending_returns_pending_and_rejected_only(tmp_db):
    """``list_pending`` filters out approved rows."""
    pending = _submit("pendingA")
    to_reject = _submit("rejectB")
    to_approve = _submit("approveC")

    db_marketplace.reject_app(to_reject["id"], moderation_notes="nope")
    db_marketplace.approve_app(to_approve["id"], moderation_notes="ok")

    rows = db_marketplace.list_pending()
    statuses = {(r["id"], r["moderation_status"]) for r in rows}
    assert (pending["id"], "pending") in statuses
    assert (to_reject["id"], "rejected") in statuses
    # Approved rows must not surface in the moderation queue.
    assert all(r["id"] != to_approve["id"] for r in rows)


def test_approve_app_is_idempotent(tmp_db):
    """Approving an already-approved app is a no-op (stays approved + public)."""
    app = _submit()
    first = db_marketplace.approve_app(app["id"], moderation_notes="ok")
    assert first["moderation_status"] == "approved"

    second = db_marketplace.approve_app(app["id"], moderation_notes="ok-again")
    assert second is not None
    assert second["moderation_status"] == "approved"
    assert second["is_public"] is True
