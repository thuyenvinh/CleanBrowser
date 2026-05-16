"""Workspace CRUD and member management endpoints (Phase 1, task M).

Endpoints mounted at ``/api/workspaces`` for the multi-tenant frontend:

* ``GET    /api/workspaces``                            — list workspaces the
  current user is a member of (with their role).
* ``POST   /api/workspaces``                            — create a workspace in
  the caller's tenant; the caller becomes its ``owner`` member.
* ``GET    /api/workspaces/{workspace_id}``             — workspace + members.
* ``POST   /api/workspaces/{workspace_id}/members``     — invite an existing
  tenant user as a member (cross-tenant invites are Phase 2).
* ``PATCH  /api/workspaces/{workspace_id}/members/{user_id}`` — change a
  member's role.
* ``DELETE /api/workspaces/{workspace_id}/members/{user_id}`` — remove a
  member (or self-remove).

Authorization rules:

* All endpoints require a JWT session (``get_current_user``).
* Reads / detail: the caller must be a member of the workspace, otherwise we
  return ``404`` to avoid leaking the existence of resources outside their
  tenant.
* Member mutations (invite / update / delete): the caller must have an
  ``owner`` or ``admin`` role in the workspace; otherwise ``403``.
* Last-owner protection: the final remaining ``owner`` cannot be removed or
  demoted — that path returns ``403``.

We intentionally do **not** use ``backend.dependencies.require_role`` here:
that helper reads the workspace id from a header / query, but every route in
this file already carries it as a path parameter. A small local helper makes
the authorization check explicit at each endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from .. import db_auth
from ..dependencies import get_current_user
from ..models import (
    InviteMemberRequest,
    UpdateMemberRoleRequest,
    WorkspaceCreate,
)

logger = logging.getLogger("cloakbrowser.workspaces")

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

# Roles permitted to mutate workspace membership.
_MEMBER_MUTATION_ROLES: tuple[str, ...] = ("owner", "admin")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_member_role(
    workspace_id: str,
    user: dict[str, Any],
    allowed: tuple[str, ...] | None = None,
) -> str:
    """Assert ``user`` is a member of ``workspace_id`` and return their role.

    Behaviour:
        * No membership → ``HTTPException(404)`` (we don't leak existence).
        * Membership exists but role not in ``allowed`` → ``HTTPException(403)``.
        * ``allowed=None`` means any role is acceptable.
    """
    try:
        role = db_auth.get_member_role(workspace_id, user["id"])
    except Exception:
        logger.exception(
            "get_member_role failed (ws=%s user=%s)",
            workspace_id,
            user.get("id"),
        )
        raise HTTPException(status_code=500, detail="role lookup failed")
    if role is None:
        # 404, not 403 — don't leak whether the workspace exists.
        raise HTTPException(status_code=404, detail="Workspace not found")
    if allowed is not None and role not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Requires one of roles: {sorted(allowed)}",
        )
    return role


def _workspace_summary(ws: dict[str, Any]) -> dict[str, Any]:
    """Project a workspace row into the response shape for the list endpoint."""
    return {
        "id": ws["id"],
        "tenant_id": ws["tenant_id"],
        "name": ws["name"],
        "owner_user_id": ws["owner_user_id"],
        "created_at": ws["created_at"],
        # ``list_workspaces_for_user`` joins workspace_members and aliases
        # the role column to ``member_role``; surface it as ``role`` to the
        # client for symmetry with the detail/member responses.
        "role": ws.get("member_role"),
    }


def _member_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": row["user_id"],
        "email": row["email"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Workspace CRUD
# ---------------------------------------------------------------------------


@router.get("")
async def list_workspaces(
    user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List workspaces the current user is a member of."""
    workspaces = db_auth.list_workspaces_for_user(user["id"])
    return [_workspace_summary(w) for w in workspaces]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a workspace in the caller's tenant; caller becomes ``owner``."""
    try:
        workspace = db_auth.create_workspace(
            tenant_id=user["tenant_id"],
            name=body.name,
            owner_user_id=user["id"],
        )
        db_auth.add_workspace_member(workspace["id"], user["id"], "owner")
    except Exception:
        logger.exception("create_workspace failed for user=%s", user["id"])
        raise HTTPException(status_code=500, detail="failed to create workspace")
    return {
        "id": workspace["id"],
        "tenant_id": workspace["tenant_id"],
        "name": workspace["name"],
        "owner_user_id": workspace["owner_user_id"],
        "created_at": workspace["created_at"],
        "role": "owner",
    }


@router.get("/{workspace_id}")
async def get_workspace_detail(
    workspace_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Workspace detail plus member list. 404 if caller isn't a member."""
    _check_member_role(workspace_id, user)
    ws = db_auth.get_workspace(workspace_id)
    if ws is None:
        # Race: membership row exists but workspace was just deleted.
        raise HTTPException(status_code=404, detail="Workspace not found")
    members = db_auth.list_workspace_members(workspace_id)
    return {
        "id": ws["id"],
        "tenant_id": ws["tenant_id"],
        "name": ws["name"],
        "owner_user_id": ws["owner_user_id"],
        "created_at": ws["created_at"],
        "members": [_member_public(m) for m in members],
    }


# ---------------------------------------------------------------------------
# Member management
# ---------------------------------------------------------------------------


@router.post(
    "/{workspace_id}/members",
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    workspace_id: str,
    body: InviteMemberRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Invite an existing tenant user to ``workspace_id``.

    Phase 1: cross-tenant invites are not supported — the target email must
    resolve to a user in the caller's tenant.
    """
    _check_member_role(workspace_id, user, _MEMBER_MUTATION_ROLES)

    target = db_auth.get_user_by_email_in_tenant(user["tenant_id"], body.email)
    if target is None:
        raise HTTPException(
            status_code=400,
            detail="No user with that email exists in this tenant",
        )

    if db_auth.get_member_role(workspace_id, target["id"]) is not None:
        raise HTTPException(
            status_code=409,
            detail="User is already a member of this workspace",
        )

    try:
        db_auth.add_workspace_member(workspace_id, target["id"], body.role)
    except ValueError as exc:
        # Invalid role string — should be caught by pydantic, but be safe.
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        logger.exception(
            "add_workspace_member failed (ws=%s user=%s)",
            workspace_id,
            target["id"],
        )
        raise HTTPException(status_code=500, detail="failed to add member")

    return {
        "user_id": target["id"],
        "email": target["email"],
        "role": body.role,
    }


@router.patch("/{workspace_id}/members/{user_id}")
async def update_member_role(
    workspace_id: str,
    user_id: str,
    body: UpdateMemberRoleRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Change a member's role. Refuses to demote the last remaining owner."""
    _check_member_role(workspace_id, user, _MEMBER_MUTATION_ROLES)

    current_role = db_auth.get_member_role(workspace_id, user_id)
    if current_role is None:
        raise HTTPException(status_code=404, detail="Member not found")

    # Last-owner protection: refuse to demote the only remaining owner.
    if current_role == "owner" and body.role != "owner":
        if db_auth.count_workspace_owners(workspace_id) <= 1:
            raise HTTPException(
                status_code=403,
                detail="cannot demote the last owner of a workspace",
            )

    try:
        updated = db_auth.update_workspace_member_role(
            workspace_id, user_id, body.role
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        logger.exception(
            "update_workspace_member_role failed (ws=%s user=%s)",
            workspace_id,
            user_id,
        )
        raise HTTPException(status_code=500, detail="failed to update role")
    if not updated:
        # Disappeared between the role check and the update — treat as 404.
        raise HTTPException(status_code=404, detail="Member not found")

    target = db_auth.get_user(user_id)
    return {
        "user_id": user_id,
        "email": target["email"] if target else None,
        "role": body.role,
    }


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    workspace_id: str,
    user_id: str,
    user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    """Remove a member from ``workspace_id``.

    A user may remove themselves; the same endpoint covers admin-driven
    removals. The last remaining owner cannot be removed (would orphan the
    workspace).
    """
    _check_member_role(workspace_id, user, _MEMBER_MUTATION_ROLES)

    target_role = db_auth.get_member_role(workspace_id, user_id)
    if target_role is None:
        raise HTTPException(status_code=404, detail="Member not found")

    if target_role == "owner":
        if db_auth.count_workspace_owners(workspace_id) <= 1:
            raise HTTPException(
                status_code=403,
                detail="cannot remove the last owner of a workspace",
            )

    try:
        removed = db_auth.remove_workspace_member(workspace_id, user_id)
    except Exception:
        logger.exception(
            "remove_workspace_member failed (ws=%s user=%s)",
            workspace_id,
            user_id,
        )
        raise HTTPException(status_code=500, detail="failed to remove member")
    if not removed:
        raise HTTPException(status_code=404, detail="Member not found")

    return Response(status_code=status.HTTP_204_NO_CONTENT)
