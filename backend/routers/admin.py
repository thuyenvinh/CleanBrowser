"""Platform-admin endpoints (cross-tenant super-admin surface).

Gated behind ``Depends(require_platform_admin)``. Non-admins get 404 so
the existence of this surface isn't leaked.

Everything in here runs inside :func:`system_context` because the admin
operates across the whole tenant population — RLS would otherwise hide
every row outside the admin's own tenant.

Audit:
    Every state-changing action emits an entry via :func:`db_audit.write`
    so promotion / demotion / disable / enable are traceable to a real
    actor (the admin's user id + IP).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .. import db_audit, db_auth, db_billing
from ..dependencies import require_platform_admin
from ..middleware_rls import system_context
from ..rate_limit import limiter

logger = logging.getLogger("cloakbrowser.admin")
router = APIRouter(prefix="/api/admin", tags=["admin"])


def _project_user(row: dict[str, Any]) -> dict[str, Any]:
    """Strip sensitive fields before returning a user row to the admin."""
    return {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "email": row["email"],
        "status": row.get("status", "active"),
        "email_verified_at": row.get("email_verified_at"),
        "is_platform_admin": bool(row.get("is_platform_admin")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _audit(actor: dict, action: str, target_id: str, request: Request, **payload: Any) -> None:
    """Best-effort audit row for an admin action."""
    try:
        with system_context():
            db_audit.write(
                action=action,
                tenant_id=actor.get("tenant_id"),
                actor_user_id=actor.get("id"),
                resource_type="user",
                resource_id=target_id,
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                status="success",
                payload=payload,
            )
    except Exception:
        logger.exception("admin audit write failed")


# ── Tenants ──────────────────────────────────────────────────────────────────


@router.get("/tenants")
@limiter.limit("60/minute")
async def list_tenants_route(
    request: Request,  # noqa: ARG001 — required by the rate limiter
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_platform_admin),
) -> list[dict[str, Any]]:
    """Cross-tenant tenant directory with user counts."""
    with system_context():
        return db_auth.list_tenants(limit=limit, offset=offset)


@router.get("/tenants/{tenant_id}")
@limiter.limit("120/minute")
async def get_tenant_route(
    tenant_id: str,
    request: Request,  # noqa: ARG001 — required by the rate limiter
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Tenant detail + active subscription snapshot."""
    with system_context():
        tenant = db_auth.get_tenant(tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        sub = db_billing.get_active_subscription(tenant_id)
        usage = db_billing.get_or_create_current_period(tenant_id)
    return {"tenant": tenant, "subscription": sub, "usage": usage}


# ── Users ────────────────────────────────────────────────────────────────────


@router.get("/users")
@limiter.limit("60/minute")
async def list_users_route(
    request: Request,  # noqa: ARG001 — required by the rate limiter
    tenant_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_platform_admin),
) -> list[dict[str, Any]]:
    """Paginated user directory; filter by tenant via ``?tenant_id=...``."""
    with system_context():
        rows = db_auth.list_users(limit=limit, offset=offset, tenant_id=tenant_id)
    return [_project_user(r) for r in rows]


@router.get("/users/{user_id}")
@limiter.limit("120/minute")
async def get_user_route(
    user_id: str,
    request: Request,  # noqa: ARG001 — required by the rate limiter
    _admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """User detail + workspace memberships across all tenants."""
    with system_context():
        user = db_auth.get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        workspaces = db_auth.list_workspaces_for_user(user_id)
    return {"user": _project_user(user), "workspaces": workspaces}


@router.post("/users/{user_id}/disable", status_code=200)
@limiter.limit("30/minute")
async def disable_user_route(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Set ``users.status='disabled'``; the user can no longer log in.

    Existing sessions keep their cookie until the next request — but
    :func:`get_optional_user` rejects users whose status is not ``active``,
    so the next API call returns 401 and the SPA boots back to login.
    """
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="cannot disable yourself")
    with system_context():
        target = db_auth.get_user(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        ok = db_auth.set_user_status(user_id, "disabled")
    if not ok:
        raise HTTPException(status_code=500, detail="status update failed")
    _audit(admin, "admin.user.disable", user_id, request)
    return {"ok": True}


@router.post("/users/{user_id}/enable", status_code=200)
@limiter.limit("30/minute")
async def enable_user_route(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Set ``users.status='active'`` (reverses ``disable``)."""
    with system_context():
        target = db_auth.get_user(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        ok = db_auth.set_user_status(user_id, "active")
    if not ok:
        raise HTTPException(status_code=500, detail="status update failed")
    _audit(admin, "admin.user.enable", user_id, request)
    return {"ok": True}


@router.post("/users/{user_id}/promote", status_code=200)
@limiter.limit("10/hour")
async def promote_user_route(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Grant the target user the platform-admin flag."""
    with system_context():
        target = db_auth.get_user(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        ok = db_auth.set_platform_admin(user_id, True)
    if not ok:
        raise HTTPException(status_code=500, detail="promote failed")
    _audit(admin, "admin.user.promote", user_id, request)
    logger.warning("admin %s promoted user %s to platform admin", admin["id"], user_id)
    return {"ok": True}


@router.post("/users/{user_id}/demote", status_code=200)
@limiter.limit("10/hour")
async def demote_user_route(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Revoke the platform-admin flag.

    A platform admin cannot demote themselves — there must always be at
    least one operator who can mint another.
    """
    if user_id == admin["id"]:
        raise HTTPException(
            status_code=400,
            detail="cannot demote yourself; ask another platform admin",
        )
    with system_context():
        target = db_auth.get_user(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        ok = db_auth.set_platform_admin(user_id, False)
    if not ok:
        raise HTTPException(status_code=500, detail="demote failed")
    _audit(admin, "admin.user.demote", user_id, request)
    logger.warning("admin %s demoted user %s", admin["id"], user_id)
    return {"ok": True}


# ── Self ─────────────────────────────────────────────────────────────────────


@router.get("/me")
@limiter.limit("120/minute")
async def admin_me(
    request: Request,  # noqa: ARG001 — required by the rate limiter
    admin: dict = Depends(require_platform_admin),
) -> dict[str, Any]:
    """Identity probe — useful for the SPA to gate the admin console UI."""
    return _project_user(admin)
