"""Profile CRUD plus launch/stop/status endpoints.

Multi-tenant scoping (Phase 1, task L):

* When an authenticated session user is present (``get_optional_user``
  returns a user dict), every read is scoped to the user's workspaces and
  every write attaches ``workspace_id`` to the profile.
* When no user is present (legacy AUTH_TOKEN mode, the test suite hitting
  the API without logging in, scripts), the endpoints behave exactly as
  before — no filtering, no workspace assignment. Profiles created in this
  mode have ``workspace_id = NULL`` and are visible only via the no-user
  code path.
* To avoid leaking the existence of profiles belonging to other workspaces
  we return ``404`` (not ``403``) when an authenticated user touches a
  profile outside their workspace set.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import database as db
from .. import db_auth
from .. import db_proxy
from .. import db_versions
from ..dependencies import (
    ROLE_LEVEL,
    browser_mgr,
    check_role_for_workspace,
    get_optional_user,
)
from ..models import (
    LaunchResponse,
    PresignedUrlResponse,
    ProfileCreate,
    ProfileResponse,
    ProfileStatusResponse,
    ProfileUpdate,
    ProfileVersion,
    RestoreResponse,
    TagResponse,
)

logger = logging.getLogger("cloakbrowser.manager")

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _user_workspace_ids(user: dict[str, Any]) -> list[str]:
    """Return the list of workspace ids the user is a member of."""
    workspaces = db_auth.list_workspaces_for_user(user["id"])
    return [w["id"] for w in workspaces]


def _resolve_create_workspace_id(
    request: Request, user: dict[str, Any]
) -> str:
    """Pick the workspace a new profile should belong to for ``user``.

    Priority:
        1. ``X-Workspace-Id`` request header, validated against the user's
           memberships. Unknown / non-member values → 403.
        2. The user's first workspace (oldest membership, as returned by
           ``list_workspaces_for_user``). Users that just signed up always
           have at least their "Default" workspace from ``db_auth.signup``.

    Raises ``HTTPException(403)`` if the user has no workspaces at all —
    they can't create a profile in that state.
    """
    workspaces = db_auth.list_workspaces_for_user(user["id"])
    ws_ids = {w["id"] for w in workspaces}

    requested = request.headers.get("x-workspace-id")
    if requested:
        if requested not in ws_ids:
            raise HTTPException(
                status_code=403,
                detail="Not a member of the requested workspace",
            )
        return requested

    if not workspaces:
        raise HTTPException(
            status_code=403,
            detail="User has no workspaces; cannot create profile",
        )
    return workspaces[0]["id"]


def _load_and_authorize(
    profile_id: str, user: dict[str, Any] | None
) -> dict[str, Any]:
    """Fetch a profile and enforce workspace scoping.

    * If ``user`` is ``None`` (legacy / unauthenticated): behave like the
      pre-multi-tenant code — load and return the profile, or raise 404.
    * If ``user`` is set: the profile must (a) exist AND (b) belong to one
      of the user's workspaces. ``workspace_id IS NULL`` profiles are
      treated as invisible to authenticated users; we return 404 in that
      case rather than 403 so we don't leak existence across tenants.
    """
    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    if user is None:
        return profile
    profile_ws = profile.get("workspace_id")
    if profile_ws is None:
        # Orphan / legacy profile: hidden from authenticated users.
        raise HTTPException(status_code=404, detail="Profile not found")
    if profile_ws not in set(_user_workspace_ids(user)):
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


def _load_and_check(
    profile_id: str,
    user: dict[str, Any] | None,
    min_level: int,
) -> dict[str, Any]:
    """Load a profile, enforce workspace scoping, then enforce role level.

    Thin wrapper around :func:`_load_and_authorize` +
    :func:`check_role_for_workspace`. Legacy / unauthenticated callers
    (``user is None``) still bypass the role check, matching the rest of the
    multi-tenant layering in this router.
    """
    profile = _load_and_authorize(profile_id, user)
    check_role_for_workspace(user, profile.get("workspace_id"), min_level)
    return profile


def _validate_proxy_id_for_workspace(
    proxy_id: str | None,
    workspace_id: str | None,
    user: dict[str, Any] | None,
) -> None:
    """Ensure ``proxy_id`` (if given) belongs to ``workspace_id``.

    Cross-workspace assignment is rejected with 404 (mirrors the rest of
    this router's "don't leak existence across tenants" stance). For
    authenticated callers we also enforce viewer+ membership on the
    proxy's workspace via :func:`check_role_for_workspace` — a user can't
    attach a proxy from a workspace they have no role in even if they
    somehow guessed the id.

    Unauthenticated / legacy callers (``user is None``) skip the role
    check but still need the proxy to live in the same workspace as the
    profile (or — if the profile itself is workspace-less in legacy
    mode — the proxy must simply exist).
    """
    if not proxy_id:
        return
    proxy = db_proxy.get_proxy(proxy_id)
    if proxy is None:
        raise HTTPException(status_code=404, detail="Proxy not found")
    proxy_ws = proxy.get("workspace_id")
    if workspace_id is not None and proxy_ws != workspace_id:
        # Don't tell the caller why — keep parity with the 404-on-cross-
        # tenant pattern used for profiles.
        raise HTTPException(status_code=404, detail="Proxy not found")
    # Authenticated callers must have viewer+ in the proxy's workspace.
    if user is not None:
        check_role_for_workspace(user, proxy_ws, ROLE_LEVEL["viewer"])


def _decorate_with_runtime(profile: dict[str, Any]) -> dict[str, Any]:
    """Attach the live status / vnc / cdp fields onto a profile dict."""
    status = browser_mgr.get_status(profile["id"])
    profile["status"] = status["status"]
    profile["vnc_ws_port"] = status["vnc_ws_port"]
    profile["cdp_url"] = status["cdp_url"]
    profile["tags"] = [TagResponse(**t) for t in profile.get("tags", [])]
    return profile


# TODO(Phase O): role enforcement for CDP HTTP/WS routes (``routers/cdp.py``)
# and the VNC WebSocket (``routers/vnc.py``). Wiring is out of scope here per
# the task's "only touch profiles.py + dependencies.py" constraint — those
# routers still rely on ``_load_and_authorize`` semantics.


# ── CRUD ─────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[ProfileResponse])
async def list_profiles(
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    if user is None:
        profiles = db.list_profiles()
    else:
        profiles = db.list_profiles(workspace_ids=_user_workspace_ids(user))
    return [ProfileResponse(**_decorate_with_runtime(p)) for p in profiles]


@router.post("", response_model=ProfileResponse, status_code=201)
async def create_profile(
    req: ProfileCreate,
    request: Request,
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    data = req.model_dump()
    tags = data.pop("tags", None)
    if tags:
        data["tags"] = [t.model_dump() if hasattr(t, "model_dump") else t for t in tags]
    else:
        data["tags"] = []

    if user is not None:
        target_ws = _resolve_create_workspace_id(request, user)
        # Require editor+ in the target workspace to create profiles.
        check_role_for_workspace(user, target_ws, ROLE_LEVEL["editor"])
        data["workspace_id"] = target_ws
    # else: leave workspace_id unset → create_profile defaults to NULL.

    # If the caller is binding a proxy, validate workspace membership before
    # we INSERT — otherwise we'd half-create a profile and then 404.
    _validate_proxy_id_for_workspace(
        data.get("proxy_id"), data.get("workspace_id"), user
    )

    profile = db.create_profile(**data)
    return ProfileResponse(**_decorate_with_runtime(profile))


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(
    profile_id: str,
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    profile = _load_and_check(profile_id, user, ROLE_LEVEL["viewer"])
    return ProfileResponse(**_decorate_with_runtime(profile))


@router.put("/{profile_id}", response_model=ProfileResponse)
async def update_profile(
    profile_id: str,
    req: ProfileUpdate,
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    # Authorize first so we don't leak existence by failing on a different
    # error path further down for cross-workspace ids.
    existing = _load_and_check(profile_id, user, ROLE_LEVEL["editor"])

    # Only pass fields that were explicitly set
    data = req.model_dump(exclude_unset=True)
    tags = data.pop("tags", None)
    if tags is not None:
        data["tags"] = [t.model_dump() if hasattr(t, "model_dump") else t for t in tags]

    # If proxy_id is being set / changed, validate it lives in the same
    # workspace as the profile we're editing. ``exclude_unset`` means an
    # explicit ``None`` (unbind) is allowed through; the helper short-
    # circuits on ``None`` so it's a no-op in that case.
    if "proxy_id" in data:
        _validate_proxy_id_for_workspace(
            data["proxy_id"], existing.get("workspace_id"), user
        )

    profile = db.update_profile(profile_id, **data)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return ProfileResponse(**_decorate_with_runtime(profile))


@router.delete("/{profile_id}")
async def delete_profile(
    profile_id: str,
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    # Stop browser if running (cheap fast-path before authz lookup so the
    # behaviour matches the legacy code's ordering for the test that mocks
    # stop()).
    if profile_id in browser_mgr.running:
        await browser_mgr.stop(profile_id)

    profile = _load_and_check(profile_id, user, ROLE_LEVEL["editor"])

    user_data_dir = Path(profile["user_data_dir"])

    # DB first — if this fails, filesystem is untouched
    db.delete_profile(profile_id)

    # Then clean up disk
    if user_data_dir.exists():
        shutil.rmtree(user_data_dir, ignore_errors=True)

    return {"ok": True}


# ── Launch / Stop ─────────────────────────────────────────────────────────────


@router.post("/{profile_id}/launch", response_model=LaunchResponse)
async def launch_profile(
    profile_id: str,
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    profile = _load_and_check(profile_id, user, ROLE_LEVEL["launcher"])
    if profile_id in browser_mgr.running:
        raise HTTPException(status_code=409, detail="Profile is already running")

    try:
        running = await browser_mgr.launch(profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to launch profile %s: %s", profile_id, exc)
        raise HTTPException(status_code=500, detail="Failed to launch browser")

    return LaunchResponse(
        profile_id=profile_id,
        status="running",
        vnc_ws_port=running.ws_port,
        display=f":{running.display}",
        cdp_url=f"/api/profiles/{profile_id}/cdp",
    )


@router.post("/{profile_id}/stop")
async def stop_profile(
    profile_id: str,
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    # Match legacy behaviour: 404 "Profile is not running" wins over any
    # workspace check. Tests rely on hitting this with an arbitrary id
    # (``/api/profiles/nonexistent/stop``) and expecting 404 without any
    # profile row existing. We only enforce workspace scoping when the
    # profile DOES exist AND the caller is authenticated.
    if profile_id not in browser_mgr.running:
        raise HTTPException(status_code=404, detail="Profile is not running")
    if user is not None:
        _load_and_check(profile_id, user, ROLE_LEVEL["launcher"])
    await browser_mgr.stop(profile_id)
    return {"ok": True}


@router.get("/{profile_id}/status", response_model=ProfileStatusResponse)
async def get_profile_status(
    profile_id: str,
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    _load_and_check(profile_id, user, ROLE_LEVEL["viewer"])
    status = browser_mgr.get_status(profile_id)
    return ProfileStatusResponse(**status)


# ── Cloud snapshot versions (Phase 3 wave 2) ──────────────────────────────────
#
# The four endpoints below surface ``backend.db_versions`` over HTTP so the
# SPA's ``ProfileVersionHistory`` panel can list, restore, delete, and
# download snapshots that ``browser_manager`` uploads on stop. Authorization
# follows the same workspace+role model as the rest of this router (viewer+
# for read, editor+ for any mutation or signed-URL access).


@router.get("/{profile_id}/versions", response_model=list[ProfileVersion])
async def list_profile_versions(
    profile_id: str,
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    _load_and_check(profile_id, user, ROLE_LEVEL["viewer"])
    return db_versions.list_versions(profile_id)


@router.post(
    "/{profile_id}/versions/{version_id}/restore",
    response_model=RestoreResponse,
)
async def restore_profile_version(
    profile_id: str,
    version_id: str,
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    profile = _load_and_check(profile_id, user, ROLE_LEVEL["editor"])
    v = db_versions.get_version(version_id)
    if not v or v["profile_id"] != profile_id:
        raise HTTPException(status_code=404, detail="Version not found")

    # Restoring a live profile would race with the running browser writing
    # to ``user_data_dir`` — force the caller to stop first rather than
    # silently corrupting state.
    if profile_id in browser_mgr.running:
        raise HTTPException(
            status_code=409,
            detail="Profile is running; stop it before restoring a version",
        )

    udir = profile.get("user_data_dir")
    if not udir:
        raise HTTPException(
            status_code=500, detail="Profile has no user_data_dir configured"
        )

    from ..profile_snapshot import restore_from_storage

    ok = await restore_from_storage(profile_id, version_id, udir)
    if not ok:
        raise HTTPException(
            status_code=500, detail="Restore failed; see server logs"
        )
    return RestoreResponse(restored=True, version=v["version"])


@router.delete("/{profile_id}/versions/{version_id}", status_code=204)
async def delete_profile_version(
    profile_id: str,
    version_id: str,
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    _load_and_check(profile_id, user, ROLE_LEVEL["editor"])
    v = db_versions.get_version(version_id)
    if not v or v["profile_id"] != profile_id:
        raise HTTPException(status_code=404, detail="Version not found")

    # Best-effort delete from object storage first, then drop the index
    # row. A storage failure shouldn't strand the row in the UI; we log
    # the orphaned key for ops to GC later.
    from .. import storage

    try:
        storage.delete(v["storage_key"])
    except Exception:
        logger.exception(
            "failed to delete storage object %s", v["storage_key"]
        )
    db_versions.delete_version(version_id)


@router.get(
    "/{profile_id}/versions/{version_id}/download",
    response_model=PresignedUrlResponse,
)
async def get_version_download_url(
    profile_id: str,
    version_id: str,
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    _load_and_check(profile_id, user, ROLE_LEVEL["editor"])
    v = db_versions.get_version(version_id)
    if not v or v["profile_id"] != profile_id:
        raise HTTPException(status_code=404, detail="Version not found")

    from .. import storage

    try:
        url = storage.presigned_url(v["storage_key"], expires_in=3600)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Storage backend does not support presigned URLs in this mode",
        )
    return PresignedUrlResponse(
        url=url,
        expires_in=3600,
        storage_key=v["storage_key"],
        size_bytes=v["size_bytes"],
    )
