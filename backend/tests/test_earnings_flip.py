"""Tests for marketplace earnings ledger + 14-day escrow flip (H8).

Each install of a paid app spawns one ``marketplace_earnings`` row in
``status='pending'`` with ``available_at = now() + 14 days``. The daily
worker (``mark_earnings_available_due``) flips ripe rows to
``status='available'`` so the creator can request payout.
"""
from __future__ import annotations

import datetime
import uuid

from backend import db_auth, db_marketplace
from backend.database import get_db


def _make_creator_and_app(slug: str) -> tuple[dict, dict]:
    """Sign up a creator, submit + approve an app, set creator_user_id.

    Returns ``(creator_user, app_row_with_creator)``. The returned app dict
    is a fresh ``SELECT`` so it carries the ``creator_user_id`` /
    ``revenue_share_pct`` columns that :func:`record_earning` reads.
    """
    _, user, _ws = db_auth.signup(
        email=f"creator+{slug}@example.test",
        password="some-secure-password",
    )
    app = db_marketplace.submit_app(
        slug=f"app-{slug}",
        name=f"App {slug}",
        description=None,
        kind="flow",
        dsl_json={"steps": []},
        script_language=None,
        script_code=None,
        creator_name="tester",
        creator_url=None,
        submitted_by_user_id=user["id"],
    )
    # ``submit_app`` doesn't populate creator_user_id (the 0025 migration
    # only backfilled existing rows). Stamp it ourselves so the ledger row
    # can attach to the creator.
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE marketplace_apps "
                "SET creator_user_id = %s, revenue_share_pct = 70 "
                "WHERE id = %s",
                (user["id"], app["id"]),
            )
        conn.commit()
    # Re-fetch with the now-populated split columns.
    fresh = db_marketplace.get_app(app["id"])
    return user, fresh


def _make_buyer() -> tuple[dict, dict]:
    """Return ``(buyer_user, buyer_workspace)`` for a separate tenant."""
    _, user, ws = db_auth.signup(
        email=f"buyer+{uuid.uuid4().hex[:8]}@example.test",
        password="some-secure-password",
    )
    return user, ws


def test_record_earning_creates_pending_row_with_14_day_escrow(tmp_db):
    """First install of a paid app spawns a ``pending`` ledger row."""
    creator, app = _make_creator_and_app(uuid.uuid4().hex[:8])
    buyer, buyer_ws = _make_buyer()

    earning = db_marketplace.record_earning(
        app=app,
        install_id=None,
        buyer_tenant_id=buyer_ws["tenant_id"],
        gross_cents=1000,
    )

    assert earning is not None
    assert earning["status"] == "pending"
    assert earning["gross_cents"] == 1000
    assert earning["creator_cents"] == 700  # 70% of 1000
    assert earning["platform_cents"] == 300
    # available_at should be ~14 days out (allow ±1h skew). The data layer
    # stringifies datetimes via ``isoformat()`` for JSON parity, so parse
    # back to compare.
    now = datetime.datetime.now(datetime.timezone.utc)
    available_at = datetime.datetime.fromisoformat(earning["available_at"])
    delta = available_at - now
    assert datetime.timedelta(days=13, hours=23) < delta < datetime.timedelta(
        days=14, hours=1
    )


def test_mark_earnings_available_due_skips_future_rows(tmp_db):
    """A row whose available_at is still in the future stays ``pending``."""
    creator, app = _make_creator_and_app(uuid.uuid4().hex[:8])
    buyer, buyer_ws = _make_buyer()

    earning = db_marketplace.record_earning(
        app=app,
        install_id=None,
        buyer_tenant_id=buyer_ws["tenant_id"],
        gross_cents=500,
    )
    # Fresh row's available_at is +14d, so the worker should be a no-op.
    flipped = db_marketplace.mark_earnings_available_due()
    assert flipped == 0

    rows = db_marketplace.list_earnings_for_creator(creator["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"


def test_mark_earnings_available_due_flips_ripe_rows(tmp_db):
    """A row whose available_at has elapsed flips to ``available``."""
    creator, app = _make_creator_and_app(uuid.uuid4().hex[:8])
    buyer, buyer_ws = _make_buyer()

    earning = db_marketplace.record_earning(
        app=app,
        install_id=None,
        buyer_tenant_id=buyer_ws["tenant_id"],
        gross_cents=2000,
    )
    # Backdate available_at by 1 hour so the worker treats it as ripe.
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE marketplace_earnings "
                "SET available_at = now() - interval '1 hour' "
                "WHERE id = %s",
                (earning["id"],),
            )
        conn.commit()

    flipped = db_marketplace.mark_earnings_available_due()
    assert flipped == 1

    rows = db_marketplace.list_earnings_for_creator(creator["id"])
    assert len(rows) == 1
    assert rows[0]["status"] == "available"


def test_list_earnings_for_creator_returns_only_their_rows(tmp_db):
    """Earnings are scoped per ``creator_user_id``."""
    creator_a, app_a = _make_creator_and_app(uuid.uuid4().hex[:8])
    creator_b, app_b = _make_creator_and_app(uuid.uuid4().hex[:8])
    buyer, buyer_ws = _make_buyer()

    db_marketplace.record_earning(
        app=app_a, install_id=None,
        buyer_tenant_id=buyer_ws["tenant_id"], gross_cents=1000,
    )
    db_marketplace.record_earning(
        app=app_b, install_id=None,
        buyer_tenant_id=buyer_ws["tenant_id"], gross_cents=300,
    )

    a_rows = db_marketplace.list_earnings_for_creator(creator_a["id"])
    b_rows = db_marketplace.list_earnings_for_creator(creator_b["id"])

    assert len(a_rows) == 1
    assert a_rows[0]["gross_cents"] == 1000
    assert len(b_rows) == 1
    assert b_rows[0]["gross_cents"] == 300
