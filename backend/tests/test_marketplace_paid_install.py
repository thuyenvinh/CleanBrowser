"""Tests for the C2 fix: paid marketplace installs route through Stripe.

The bug: paid app installs recorded a creator earning even when the buyer
was never charged. The fix splits the install into two phases:

1. Insert a ``marketplace_pending_installs`` row keyed by the Stripe
   checkout session id (status='pending').
2. On Stripe redirect callback, flip pending → completed, then run the
   real install + record_earning.

We exercise the data-layer surface (record_pending_install,
get_pending_install_by_session, complete_pending_install, record_earning).
"""
from __future__ import annotations

import uuid

import pytest

from backend import db_auth, db_marketplace
from backend.database import get_db


def _make_user(tmp_db) -> dict:
    """Sign up a user → ``{id, email, tenant_id, workspace_id}``."""
    _, user, ws = db_auth.signup(
        email=f"mkt+{uuid.uuid4().hex[:8]}@example.test",
        password="password123",
    )
    user["workspace_id"] = ws["id"]
    user["tenant_id"] = ws["tenant_id"]
    return user


def _insert_app(
    *,
    name: str = "Test App",
    price_cents: int = 0,
    creator_user_id: str | None = None,
    revenue_share_pct: int = 70,
) -> dict:
    """Insert a minimal marketplace_apps row and return it.

    Bypasses the submit_app moderation flow — we want a row that's
    immediately usable from the install endpoint.
    """
    app_id = str(uuid.uuid4())
    slug = f"test-app-{uuid.uuid4().hex[:8]}"
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO marketplace_apps (
                       id, slug, name, kind, is_public, is_official,
                       moderation_status, price_cents, creator_user_id,
                       revenue_share_pct
                   ) VALUES (
                       %s, %s, %s, 'flow', true, false,
                       'approved', %s, %s, %s
                   )""",
                (
                    app_id,
                    slug,
                    name,
                    price_cents,
                    creator_user_id,
                    revenue_share_pct,
                ),
            )
        conn.commit()
    return db_marketplace.get_app(app_id)


def test_record_pending_install_writes_pending_row(tmp_db):
    """record_pending_install returns a row with status='pending'."""
    user = _make_user(tmp_db)
    app = _insert_app(price_cents=2999)
    session_id = f"cs_test_{uuid.uuid4().hex}"
    row = db_marketplace.record_pending_install(
        app_id=app["id"],
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        stripe_session_id=session_id,
    )
    assert row is not None
    assert row["status"] == "pending"
    assert row["stripe_session_id"] == session_id
    assert row["app_id"] == app["id"]


def test_get_pending_install_by_session_roundtrip(tmp_db):
    """Lookup by stripe_session_id returns the freshly created pending row."""
    user = _make_user(tmp_db)
    app = _insert_app(price_cents=999)
    session_id = f"cs_test_{uuid.uuid4().hex}"
    db_marketplace.record_pending_install(
        app_id=app["id"],
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        stripe_session_id=session_id,
    )
    found = db_marketplace.get_pending_install_by_session(session_id)
    assert found is not None
    assert found["app_id"] == app["id"]
    assert found["status"] == "pending"


def test_complete_pending_install_flips_status(tmp_db):
    """complete_pending_install moves the row pending → completed."""
    user = _make_user(tmp_db)
    app = _insert_app(price_cents=499)
    session_id = f"cs_test_{uuid.uuid4().hex}"
    pending = db_marketplace.record_pending_install(
        app_id=app["id"],
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        stripe_session_id=session_id,
    )
    assert pending["status"] == "pending"

    db_marketplace.complete_pending_install(pending["id"])

    refreshed = db_marketplace.get_pending_install_by_session(session_id)
    assert refreshed["status"] == "completed"


def test_record_earning_skipped_for_free_app(tmp_db):
    """record_earning returns None when gross_cents <= 0 (free app)."""
    user = _make_user(tmp_db)
    app = _insert_app(price_cents=0, creator_user_id=user["id"])
    out = db_marketplace.record_earning(
        app=app,
        install_id=None,
        buyer_tenant_id=user["tenant_id"],
        gross_cents=0,
    )
    assert out is None


def test_record_earning_70_30_split(tmp_db):
    """Default revenue_share_pct=70 → creator gets 70%, platform 30%."""
    user = _make_user(tmp_db)
    app = _insert_app(
        price_cents=1000, creator_user_id=user["id"], revenue_share_pct=70
    )
    row = db_marketplace.record_earning(
        app=app,
        install_id=None,
        buyer_tenant_id=user["tenant_id"],
        gross_cents=1000,
    )
    assert row is not None
    assert row["gross_cents"] == 1000
    assert row["creator_cents"] == 700
    assert row["platform_cents"] == 300
    assert row["status"] == "pending"
