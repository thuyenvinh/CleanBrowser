"""Proxy CRUD endpoints (Phase 2, wave 5).

Workspace-scoped HTTP API on top of :mod:`backend.db_proxy`. Mirrors the
auth / role pattern used by :mod:`backend.routers.profiles` and
:mod:`backend.routers.workspaces`:

* Every endpoint requires an authenticated session
  (``Depends(get_current_user)``) — there is no AUTH_TOKEN-only fallback
  for proxies, they only ever existed in the multi-tenant world.
* Workspace context is taken from the ``X-Workspace-Id`` request header
  (when creating / listing) or derived from the resource itself (when the
  proxy id is in the path).
* Role checks use :data:`ROLE_LEVEL`:
    - ``viewer`` (1)   → list / get
    - ``launcher`` (2) → manual health-check test
    - ``editor`` (3)   → create / update / delete
* To avoid leaking the existence of proxies across tenants, missing
  membership returns ``404`` (via :func:`check_role_for_workspace`), not
  ``403``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from .. import db_auth
from .. import db_proxy
from ..dependencies import (
    ROLE_LEVEL,
    check_role_for_workspace,
    get_current_user,
)
from ..models import (
    Proxy,
    ProxyBulkCreate,
    ProxyBulkResult,
    ProxyCreate,
    ProxyUpdate,
)

logger = logging.getLogger("cloakbrowser.proxy")

router = APIRouter(prefix="/api/proxies", tags=["proxies"])


# ── Helpers ──────────────────────────────────────────────────────────────────


def _resolve_workspace_for_request(
    request: Request, user: dict[str, Any], min_level: int
) -> str:
    """Pick the workspace for a list/create call and enforce ``min_level``.

    Priority:
        1. ``X-Workspace-Id`` header — validated via
           :func:`check_role_for_workspace` (404 if not a member, 403 if
           role too low).
        2. The user's first workspace (oldest membership). Users that just
           signed up always have at least their "Default" workspace.

    Raises ``HTTPException(403)`` when the user has no workspaces at all.
    """
    requested = request.headers.get("x-workspace-id")
    if requested:
        check_role_for_workspace(user, requested, min_level)
        return requested

    workspaces = db_auth.list_workspaces_for_user(user["id"])
    if not workspaces:
        raise HTTPException(
            status_code=403,
            detail="User has no workspaces; cannot access proxies",
        )
    ws_id = workspaces[0]["id"]
    check_role_for_workspace(user, ws_id, min_level)
    return ws_id


def _load_and_check_proxy(
    proxy_id: str, user: dict[str, Any], min_level: int
) -> dict[str, Any]:
    """Fetch a proxy and enforce workspace membership + role level.

    Returns the proxy row (``password_enc`` already stripped by
    :func:`db_proxy.get_proxy`). Raises:
      * 404 if the proxy doesn't exist OR the caller isn't a member of
        its workspace (existence is hidden across tenants).
      * 403 if the caller's role is below ``min_level``.
    """
    proxy = db_proxy.get_proxy(proxy_id)
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    # check_role_for_workspace raises 404 on non-membership with the
    # default "Profile not found" detail; remap to a proxy-specific
    # message to keep responses consistent with this router.
    try:
        check_role_for_workspace(user, proxy.get("workspace_id"), min_level)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Proxy not found")
        raise
    return proxy


# ── CRUD ─────────────────────────────────────────────────────────────────────


@router.get("", response_model=list[Proxy])
async def list_proxies(
    request: Request,
    status: str | None = Query(
        default=None,
        pattern="^(ok|fail|unchecked)$",
        description="Filter by health-check status.",
    ),
    user: dict[str, Any] = Depends(get_current_user),
):
    ws_id = _resolve_workspace_for_request(request, user, ROLE_LEVEL["viewer"])
    rows = db_proxy.list_proxies(ws_id, status=status)
    return [Proxy(**r) for r in rows]


@router.post("", response_model=Proxy, status_code=201)
async def create_proxy(
    req: ProxyCreate,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    ws_id = _resolve_workspace_for_request(request, user, ROLE_LEVEL["editor"])
    data = req.model_dump()
    try:
        row = db_proxy.create_proxy(workspace_id=ws_id, **data)
    except ValueError as exc:
        # Bad type / port — surface as 400.
        raise HTTPException(status_code=400, detail=str(exc))
    return Proxy(**row)


@router.post("/bulk", response_model=ProxyBulkResult)
async def bulk_create_proxies(
    req: ProxyBulkCreate,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Best-effort bulk import of proxies from CSV / paste UIs.

    Each row is inserted independently; a failure on row *i* only excludes
    that row from the result and is reported via ``failed=[{index, error}]``.
    There is no overall rollback — partial success is the expected outcome
    when users paste mixed input from spreadsheets / provider dashboards.
    The 500-entry cap is enforced by :class:`ProxyBulkCreate` (422 otherwise).
    """
    ws_id = _resolve_workspace_for_request(request, user, ROLE_LEVEL["editor"])

    created_rows: list[Proxy] = []
    failed: list[dict] = []
    for idx, item in enumerate(req.proxies):
        try:
            row = db_proxy.create_proxy(workspace_id=ws_id, **item.model_dump())
            created_rows.append(Proxy(**row))
        except ValueError as exc:
            failed.append({"index": idx, "error": str(exc)})
        except Exception as exc:  # DB / unexpected — still best-effort
            logger.exception("bulk create_proxy failed at index %d", idx)
            failed.append(
                {"index": idx, "error": str(exc) or exc.__class__.__name__}
            )

    return ProxyBulkResult(
        created=len(created_rows),
        failed=failed,
        proxies=created_rows,
    )


@router.get("/{proxy_id}", response_model=Proxy)
async def get_proxy(
    proxy_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    row = _load_and_check_proxy(proxy_id, user, ROLE_LEVEL["viewer"])
    return Proxy(**row)


@router.put("/{proxy_id}", response_model=Proxy)
async def update_proxy(
    proxy_id: str,
    req: ProxyUpdate,
    user: dict[str, Any] = Depends(get_current_user),
):
    _load_and_check_proxy(proxy_id, user, ROLE_LEVEL["editor"])
    fields = req.model_dump(exclude_unset=True)
    try:
        row = db_proxy.update_proxy(proxy_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if row is None:
        # Lost the row between authz and update (rare race).
        raise HTTPException(status_code=404, detail="Proxy not found")
    return Proxy(**row)


@router.delete("/{proxy_id}", status_code=204)
async def delete_proxy(
    proxy_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    _load_and_check_proxy(proxy_id, user, ROLE_LEVEL["editor"])
    db_proxy.delete_proxy(proxy_id)
    return Response(status_code=204)


@router.get("/{proxy_id}/usage")
def get_proxy_usage(
    proxy_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """List profiles currently using this proxy. For delete-confirm dialog.

    Inlined here (instead of growing :mod:`backend.db_proxy`) so this UX wave
    doesn't churn the data layer — see RULES in the task brief. Viewer role
    is sufficient: callers need to *see* impact before deciding to delete.
    """
    _load_and_check_proxy(proxy_id, user, ROLE_LEVEL["viewer"])
    import psycopg2.extras

    from ..database import get_db

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, name FROM profiles WHERE proxy_id = %s",
                (proxy_id,),
            )
            return {"profiles": [dict(r) for r in cur.fetchall()]}


# ── Manual health-check ──────────────────────────────────────────────────────


@router.post("/{proxy_id}/test")
async def test_proxy(
    proxy_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Synchronously probe a proxy and persist the result.

    Hits ``https://api.ipify.org`` through the proxy with a 10s timeout.
    On success / failure the row is updated via
    :func:`db_proxy.update_proxy_health` and the new state is returned.
    The async worker that does this on a schedule lands in a sibling
    Phase 2 task; this endpoint exists so operators / the UI can force
    an immediate retest.
    """
    _load_and_check_proxy(proxy_id, user, ROLE_LEVEL["launcher"])

    # Lazy-import httpx so the rest of the router still works in
    # environments where the dependency hasn't been added yet (Agent V's
    # branch). 503 keeps the contract explicit instead of 500-ing.
    try:
        import httpx  # noqa: WPS433  (intentional lazy import)
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="health check not yet available",
        )

    try:
        proxy_url = db_proxy.build_proxy_url(proxy_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Proxy not found")

    started = time.monotonic()
    try:
        resp = httpx.get(
            "https://api.ipify.org?format=json",
            proxies={"all://": proxy_url},
            timeout=10.0,
        )
        resp.raise_for_status()
    except Exception as exc:  # network error, timeout, non-2xx, etc.
        err = str(exc) or exc.__class__.__name__
        db_proxy.update_proxy_health(
            proxy_id, status="fail", last_error=err
        )
        return {
            "status": "fail",
            "latency_ms": None,
            "country_code": None,
            "error": err,
        }

    latency_ms = int((time.monotonic() - started) * 1000)

    # Country detection lives in Agent W's geoip module; import optionally
    # and stay silent if it isn't on the branch yet.
    country_code: str | None = None
    try:
        from .. import geoip  # type: ignore[attr-defined]

        lookup = getattr(geoip, "country_for_response", None)
        if callable(lookup):
            country_code = lookup(resp)
    except ImportError:
        country_code = None
    except Exception:
        logger.exception("geoip lookup failed for proxy %s", proxy_id)
        country_code = None

    db_proxy.update_proxy_health(
        proxy_id,
        status="ok",
        latency_ms=latency_ms,
        last_error=None,
        country_code=country_code,
    )
    return {
        "status": "ok",
        "latency_ms": latency_ms,
        "country_code": country_code,
    }
