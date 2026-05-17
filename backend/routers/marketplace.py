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

from fastapi import APIRouter, Depends, HTTPException

from .. import db_auth, db_automation, db_marketplace
from ..dependencies import (
    ROLE_LEVEL,
    check_role_for_workspace,
    get_current_user,
    get_optional_user,
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


@router.post("/apps/{app_id}/install")
def install_app(
    app_id: str,
    body: dict[str, Any] | None = None,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Clone an app into the caller's workspace and record the install.

    Body shape: ``{"workspace_id": "..."}``. ``workspace_id`` defaults to
    the user's first workspace when missing — matches the convenience
    fallback used by the automation endpoints.

    Cross-table choreography (kept in the router so the data layer stays
    focused on its own tables):

    1. Resolve and load the app (404 if missing or non-public).
    2. Enforce editor+ on the target workspace.
    3. Create a new ``automations`` row + first ``automation_versions``
       row carrying the app's DSL / script payload.
    4. Record the install ledger row (idempotent on
       ``(workspace_id, app_id)``); a second install of the same app
       therefore creates a *new* automation but reuses the install row.

    Returns ``{install, automation, version}`` so the client can deep-link
    straight to the freshly-cloned automation editor.
    """
    body = body or {}
    app = db_marketplace.get_app(app_id)
    if not app or not app.get("is_public"):
        raise HTTPException(status_code=404, detail="App not found")

    ws_id = body.get("workspace_id") or _first_workspace(user["id"])
    check_role_for_workspace(user, ws_id, ROLE_LEVEL["editor"])

    # Clone bundle into a fresh automation. Name comes from the app so
    # the user can spot it in their automations list immediately; they
    # can rename later via the automation CRUD endpoints.
    auto = db_automation.create_automation(
        workspace_id=ws_id,
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
        workspace_id=ws_id,
        app_id=app_id,
        user_id=user["id"],
        automation_id=auto["id"],
    )

    return {"install": install, "automation": auto, "version": version}


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
    user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List apps awaiting moderation.

    Phase 6 phase 2: any authenticated user can view the queue — good
    enough for solo / small-team deploys where the operator is also the
    sole submitter. A proper super-admin check (tenant-level role) is
    deferred to Phase 6 phase 3 when the admin console lands.
    """
    _ = user  # acknowledged: auth is the only gate this phase
    return db_marketplace.list_pending()


@router.post("/admin/apps/{app_id}/approve")
def admin_approve(
    app_id: str,
    body: dict[str, Any] | None = None,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Approve a pending submission — flips it to public + approved."""
    _ = user
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
    user: dict[str, Any] = Depends(get_current_user),
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
