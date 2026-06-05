"""Marketplace HTTP API (Phase 6, task PPP).

Public catalog browse + install/uninstall endpoints over the
``marketplace_apps`` / ``tenant_app_installs`` tables introduced by
migration ``0018_add_marketplace``. Mirrors ``docs/ARCHITECTURE`` §2.6's
sketch of an automation app store analogous to GemStore / GPM.

Auth surface:

* ``GET /apps``, ``GET /apps/{id}`` — public, no auth required. The
  catalog is meant to be browse-able by anyone evaluating the product
  (same reason the GitHub Marketplace listing is public).
* ``POST /apps/{id}/install``, ``DELETE /installs/{id}``,
  ``GET /installs`` — require a session + editor+ in the target
  workspace. Install clones the app's DSL into a new automation in the
  caller's workspace then records the install ledger row in a single
  request (no separate "create automation then attach" flow exposed to
  the client).

Phase 6 phase 1: no revenue share, no ratings, no creator self-publish,
no paid apps. The schema has room for ``is_official`` + creator metadata
but no UI surface beyond the badge yet.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import db_auth, db_automation, db_marketplace
from ..dependencies import (
    ROLE_LEVEL,
    check_role_for_workspace,
    get_current_user,
    get_optional_user,
    require_platform_admin,
)

logger = logging.getLogger("cloakbrowser.marketplace")

router = APIRouter(prefix="/api/marketplace", tags=["marketplace"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _first_workspace(user_id: str) -> str:
    """Return the user's oldest workspace id, 403 if they have none.

    Matches the fallback pattern used in :mod:`backend.routers.automations`
    and :mod:`backend.routers.proxies` for endpoints that don't carry an
    explicit ``X-Workspace-Id`` header / body field.
    """
    wss = db_auth.list_workspaces_for_user(user_id)
    if not wss:
        raise HTTPException(
            status_code=403, detail="No workspace available"
        )
    return wss[0]["id"]


# ── Public catalog ───────────────────────────────────────────────────────────


@router.get("/apps")
def list_public_apps(
    category: str | None = None,
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> list[dict[str, Any]]:
    """Public listing — no auth required.

    The ``_user`` dependency is accepted (and ignored) so the auth
    middleware records who browsed if a session cookie happens to be
    present, without rejecting anonymous traffic.
    """
    return db_marketplace.list_public_apps(category=category)


@router.get("/apps/{app_id}")
def get_app(
    app_id: str,
    _user: dict[str, Any] | None = Depends(get_optional_user),
) -> dict[str, Any]:
    """Fetch full app detail (including DSL / script payload).

    Hides non-public rows behind 404 so a leaked id doesn't reveal
    existence of draft / unlisted apps to anonymous visitors.
    """
    app = db_marketplace.get_app(app_id)
    if not app or not app.get("is_public"):
        raise HTTPException(status_code=404, detail="App not found")
    return app


# ── Install / uninstall ──────────────────────────────────────────────────────


def _do_install(
    app: dict[str, Any],
    workspace_id: str,
    user: dict[str, Any],
) -> dict[str, Any]:
    """Clone the app DSL + record the install ledger + earning.

    Shared by the free-app fast path (``install_app``) and the paid-app
    callback (``install_complete``). Kept module-private because both
    callers have already done the auth + payment checks specific to
    their flow — this helper trusts its inputs.

    Returns ``{install, automation, version}`` so the free path can
    return it directly and the callback path can log structured details.
    """
    auto = db_automation.create_automation(
        workspace_id=workspace_id,
        name=app["name"],
        kind=app["kind"],
        description=app.get("description"),
    )
    version = db_automation.create_version(
        automation_id=auto["id"],
        kind=app["kind"],
        dsl_json=app.get("dsl_json"),
        script_language=app.get("script_language"),
        script_code=app.get("script_code"),
        created_by_user_id=user["id"],
    )
    install = db_marketplace.install_app(
        workspace_id=workspace_id,
        app_id=app["id"],
        user_id=user["id"],
        automation_id=auto["id"],
    )

    # Earning is recorded only after the install ledger row exists. For
    # paid apps we additionally only reach this branch via the Stripe
    # callback (i.e. the buyer was actually charged) — bug C2 fix.
    price_cents = int(app.get("price_cents") or 0)
    if price_cents > 0 and install is not None:
        try:
            db_marketplace.record_earning(
                app=app,
                install_id=install.get("id"),
                buyer_tenant_id=user["tenant_id"],
                gross_cents=price_cents,
            )
        except Exception:
            # Earning failures must not break the install path: the
            # buyer's payment has already cleared and the automation
            # clone exists. Surface via logs so ops can reconcile.
            logger.exception(
                "marketplace.record_earning failed app=%s install=%s",
                app["id"],
                install.get("id"),
            )

    return {"install": install, "automation": auto, "version": version}


@router.post("/apps/{app_id}/install")
def install_app(
    app_id: str,
    body: dict[str, Any] | None = None,
    user: dict[str, Any] = Depends(get_current_user),
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Clone an app into the caller's workspace (free) or kick off a
    Stripe one-time checkout (paid).

    Body shape: ``{"workspace_id": "..."}``. ``workspace_id`` defaults to
    the user's first workspace when missing — matches the convenience
    fallback used by the automation endpoints.

    Free apps install synchronously (clone DSL + record install ledger)
    and return ``{install, automation, version}``.

    Paid apps (``price_cents > 0``) cannot install in this handler — bug
    C2 was that the previous flow recorded a creator earning without
    ever charging the buyer. We instead:

    1. Create a Stripe Checkout session in ``mode='payment'`` priced at
       ``price_cents``.
    2. Persist a ``marketplace_pending_installs`` row keyed by the
       checkout session id so :func:`install_complete` (the redirect
       target) can resume.
    3. Return ``{checkout_url, session_id, requires_payment: true}`` —
       the frontend's existing "Install" button just navigates to
       ``checkout_url`` and Stripe handles the card collection.

    The actual DSL clone + earning recording happens in
    :func:`install_complete` once Stripe confirms ``payment_status =
    'paid'`` on the session.
    """
    body = body or {}
    app = db_marketplace.get_app(app_id)
    if not app or not app.get("is_public"):
        raise HTTPException(status_code=404, detail="App not found")

    ws_id = body.get("workspace_id") or _first_workspace(user["id"])
    check_role_for_workspace(user, ws_id, ROLE_LEVEL["editor"])

    price_cents = int(app.get("price_cents") or 0)

    # Free app → install immediately.
    if price_cents <= 0:
        return _do_install(app, ws_id, user)

    # Paid app → defer install behind Stripe checkout. Block the request
    # cleanly if Stripe isn't wired up rather than silently falling back
    # to the broken free-install path (that was the C2 bug).
    from ..billing import stripe_adapter

    if not stripe_adapter.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Payment not configured — cannot install paid app",
        )

    customer_id = stripe_adapter.create_or_get_customer(
        tenant_id=user["tenant_id"],
        email=user["email"],
    )
    base = str(request.base_url).rstrip("/") if request is not None else ""
    # Stripe substitutes ``{CHECKOUT_SESSION_ID}`` into success_url so the
    # callback can recover its context without trusting client state.
    success_url = (
        f"{base}/api/marketplace/install/complete"
        "?session_id={CHECKOUT_SESSION_ID}"
    )
    cancel_url = f"{base}/?marketplace=cancelled"

    session = stripe_adapter.create_one_time_checkout(
        customer_id=customer_id,
        amount_cents=price_cents,
        currency="usd",
        name=f"App: {app['name']}",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={
            "tenant_id": user["tenant_id"],
            "workspace_id": ws_id,
            "user_id": user["id"],
            "app_id": app_id,
            "type": "marketplace_install",
        },
    )

    db_marketplace.record_pending_install(
        app_id=app_id,
        workspace_id=ws_id,
        user_id=user["id"],
        stripe_session_id=session["session_id"],
    )

    logger.info(
        "marketplace.install.checkout app=%s user=%s ws=%s session=%s",
        app_id,
        user["id"],
        ws_id,
        session["session_id"],
    )

    return {
        "checkout_url": session["url"],
        "session_id": session["session_id"],
        "requires_payment": True,
    }


@router.get("/install/complete")
def install_complete(session_id: str):
    """Stripe redirect target after a paid-install checkout completes.

    Re-verifies ``payment_status == 'paid'`` against Stripe (so a
    crafted redirect from a browser bookmark can't trigger a free
    install) and then runs :func:`_do_install` with the buyer's
    workspace + user resolved out of the pending row.

    Returns a ``RedirectResponse`` rather than JSON because the buyer
    lands here via Stripe's browser navigation, not via the frontend's
    fetch layer. Status query strings let the SPA show the right toast:
    ``installed`` / ``invalid`` / ``unpaid`` / ``verify_failed``.
    """
    pending = db_marketplace.get_pending_install_by_session(session_id)
    if not pending or pending.get("status") != "pending":
        return RedirectResponse("/?marketplace=invalid", status_code=302)

    # Verify payment really cleared. Hitting Stripe (not just trusting
    # the redirect) is the load-bearing check that closes C2.
    try:
        import os

        import stripe

        stripe.api_key = os.environ["STRIPE_SECRET_KEY"]
        s = stripe.checkout.Session.retrieve(session_id)
        if getattr(s, "payment_status", None) != "paid":
            logger.warning(
                "marketplace.install.complete unpaid session=%s status=%s",
                session_id,
                getattr(s, "payment_status", None),
            )
            return RedirectResponse(
                "/?marketplace=unpaid", status_code=302
            )
    except Exception:
        logger.exception(
            "marketplace.install.complete verify failed session=%s",
            session_id,
        )
        return RedirectResponse(
            "/?marketplace=verify_failed", status_code=302
        )

    app = db_marketplace.get_app(pending["app_id"])
    if app is None:
        return RedirectResponse("/?marketplace=invalid", status_code=302)

    # The callback has no session cookie (Stripe-initiated navigation),
    # so we rehydrate the buyer dict from the pending row. ``_do_install``
    # only reads ``id`` + ``tenant_id`` off it.
    buyer = db_auth.get_user(pending["user_id"])
    if buyer is None:
        return RedirectResponse("/?marketplace=invalid", status_code=302)

    _do_install(app, pending["workspace_id"], buyer)
    db_marketplace.complete_pending_install(pending["id"])

    logger.info(
        "marketplace.install.complete ok app=%s user=%s ws=%s",
        pending["app_id"],
        pending["user_id"],
        pending["workspace_id"],
    )
    return RedirectResponse("/?marketplace=installed", status_code=302)


@router.delete("/installs/{install_id}")
def uninstall(
    install_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Remove an install row (does NOT delete the cloned automation).

    Phase 6 phase 1: list the tenant's installs, find the requested
    install, and verify editor+ in that install's workspace. We
    deliberately keep the cloned automation around — uninstall means
    "remove from My Apps", not "destroy my work".
    """
    installs = db_marketplace.list_installs(user["tenant_id"])
    row = next((i for i in installs if i["id"] == install_id), None)
    if not row:
        raise HTTPException(status_code=404, detail="Install not found")
    check_role_for_workspace(user, row["workspace_id"], ROLE_LEVEL["editor"])
    db_marketplace.uninstall_app(row["workspace_id"], row["app_id"])
    return {"uninstalled": True}


@router.get("/installs")
def list_my_installs(
    user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Return every install across the caller's tenant.

    Phase 6 phase 1 scope: no per-workspace filter / pagination — the
    expected fan-out (~handful of apps per tenant in the demo period) is
    cheap to ship in one payload, and the UI can filter client-side.
    """
    return db_marketplace.list_installs(user["tenant_id"])


# ── Creator portal (Phase 6 phase 2) ─────────────────────────────────────────


@router.post("/apps/submit", status_code=201)
def submit_app(
    body: dict[str, Any],
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Submit a new app for moderation review.

    Lands in ``moderation_status='pending'`` with ``is_public=false`` so
    the row stays invisible to the public listing until an admin acts on
    it via the queue below. Slug uniqueness is checked up-front with a
    friendly 409 rather than letting the column UNIQUE constraint surface
    as an opaque 500.
    """
    slug = (body.get("slug") or "").strip()
    if not slug or not slug.replace("-", "").isalnum():
        raise HTTPException(
            status_code=400,
            detail="slug must be alphanumeric with dashes",
        )
    if db_marketplace.get_app_by_slug(slug):
        raise HTTPException(status_code=409, detail="slug already taken")

    name = (body.get("name") or "").strip()
    if not name or len(name) > 200:
        raise HTTPException(
            status_code=400, detail="name 1-200 chars required"
        )

    kind = body.get("kind", "flow")
    if kind not in ("flow", "script"):
        raise HTTPException(
            status_code=400, detail="kind must be 'flow' or 'script'"
        )

    dsl = body.get("dsl_json")
    if kind == "flow" and (
        not isinstance(dsl, dict) or "nodes" not in dsl
    ):
        raise HTTPException(
            status_code=400,
            detail="flow kind requires dsl_json with nodes",
        )

    app = db_marketplace.submit_app(
        slug=slug,
        name=name,
        description=body.get("description"),
        long_description=body.get("long_description"),
        kind=kind,
        dsl_json=dsl,
        script_language=body.get("script_language"),
        script_code=body.get("script_code"),
        category=body.get("category"),
        icon_url=body.get("icon_url"),
        creator_name=body.get("creator_name") or user.get("email"),
        creator_url=body.get("creator_url"),
        submitted_by_user_id=user["id"],
    )
    logger.info(
        "marketplace.submit slug=%s user=%s kind=%s",
        slug,
        user.get("id"),
        kind,
    )
    return app


@router.get("/admin/pending")
def list_pending_apps(
    user: dict[str, Any] = Depends(require_platform_admin),
) -> list[dict[str, Any]]:
    """List apps awaiting moderation. Platform-admin only."""
    _ = user
    return db_marketplace.list_pending()


@router.post("/admin/apps/{app_id}/approve")
def admin_approve(
    app_id: str,
    body: dict[str, Any] | None = None,
    user: dict[str, Any] = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Approve a pending submission — flips it to public + approved."""
    body = body or {}
    app = db_marketplace.approve_app(
        app_id, moderation_notes=body.get("notes")
    )
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    logger.info("marketplace.approve app=%s by=%s", app_id, user.get("id"))
    return app


@router.post("/admin/apps/{app_id}/reject")
def admin_reject(
    app_id: str,
    body: dict[str, Any],
    user: dict[str, Any] = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Reject a pending submission. Rejection notes are required so the
    creator gets actionable feedback in their submission history."""
    notes = (body.get("notes") or "").strip()
    if not notes:
        raise HTTPException(
            status_code=400, detail="rejection notes required"
        )
    app = db_marketplace.reject_app(app_id, moderation_notes=notes)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    logger.info("marketplace.reject app=%s by=%s", app_id, user.get("id"))
    return app


# ── Creator dashboard (Phase 6 phase 3) ──────────────────────────────────────
#
# Per-creator surface so users who shipped an app can track installs and
# earnings without going through the admin queue. Auth gate is the bare
# session — the data layer scopes every query on ``creator_user_id =
# user['id']`` so a logged-in user can only see their own earnings.


@router.get("/creator/earnings")
def list_my_earnings(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Earnings rows + headline counters for the logged-in creator.

    Returns ``{summary, earnings}`` in one payload so the dashboard's
    summary cards and ledger table can hydrate from a single round-trip.
    ``earnings`` is capped at 100 — the dashboard paginates client-side
    for now; if a top creator outgrows the cap we can swap in keyset
    pagination without changing the response envelope.
    """
    return {
        "summary": db_marketplace.creator_summary(user["id"]),
        "earnings": db_marketplace.list_earnings_for_creator(
            user["id"], limit=100
        ),
    }


@router.get("/creator/apps")
def list_my_apps(
    user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Apps where the user is creator — includes pending / rejected rows.

    The public ``/apps`` listing only returns approved + public rows, so
    a creator with a pending submission has no other way to see it in the
    UI. This endpoint surfaces every moderation state so the dashboard
    can show a "your submissions" table next to the earnings ledger.
    """
    return db_marketplace.list_apps_by_creator(user["id"])
