"""Automation HTTP API (Phase 4, task FF).

CRUD over the ``automations`` / ``automation_versions`` / ``automation_runs``
tables introduced by migration ``0008_add_automations``, plus a "run now"
endpoint that fires a flow against a profile's CDP URL via
:class:`backend.automation.FlowInterpreter`.

Auth / RBAC mirrors :mod:`backend.routers.proxies`:

* All routes require an authenticated session (``Depends(get_current_user)``)
  — there is no AUTH_TOKEN-only fallback for automations.
* Workspace context for list / create comes from the ``X-Workspace-Id``
  header (else the user's first workspace).
* Workspace context for resource paths (``/{automation_id}/...``) is the
  resource's own ``workspace_id``.
* 404 (not 403) is used to hide existence across tenants.

Role floors:

* ``viewer``   (1): list, get, list versions, list runs, get run.
* ``launcher`` (2): trigger a run (``POST /{id}/run``).
* ``editor``   (3): create / update / delete automation, create version.

Run execution is fire-and-forget in Phase 4 phase 1: the endpoint creates
the run row in ``status='queued'``, schedules a background task, and
returns ``202`` immediately. The background task connects to the
profile's CDP URL via Playwright, runs the flow, and writes the final
status / log / result back to the row. No queue, no scheduler — those
land in later tasks.

Imports of :mod:`backend.db_automation` and
:mod:`backend.automation.FlowInterpreter` are deferred to call sites so
this router still imports cleanly when those siblings (agents CC / EE)
haven't merged yet. The endpoints themselves will 500 in that case,
which is acceptable for the interleave window.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from .. import db_auth
from ..dependencies import (
    ROLE_LEVEL,
    browser_mgr,
    check_role_for_workspace,
    get_current_user,
)
from ..models import Schedule, ScheduleCreate, ScheduleUpdate

logger = logging.getLogger("cloakbrowser.automation")

router = APIRouter(prefix="/api/automations", tags=["automations"])


# ── Pydantic models ──────────────────────────────────────────────────────────
#
# These live in the router rather than ``backend.models`` to keep the
# task's "only touch automations.py + main.py" constraint honest. They
# mirror the column shape from migration 0008_add_automations.


class AutomationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    kind: str = Field(..., pattern="^(flow|script)$")
    description: str | None = None


class AutomationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class Automation(BaseModel):
    id: str
    workspace_id: str
    name: str
    kind: str
    description: str | None = None
    latest_version_id: str | None = None
    created_at: Any | None = None
    updated_at: Any | None = None


class AutomationVersionCreate(BaseModel):
    dsl_json: dict[str, Any] | None = None
    script_language: str | None = Field(
        default=None, pattern="^(typescript|python)$"
    )
    script_code: str | None = None


class AutomationVersion(BaseModel):
    id: str
    automation_id: str
    version: int
    kind: str
    dsl_json: dict[str, Any] | None = None
    script_language: str | None = None
    script_code: str | None = None
    created_at: Any | None = None
    created_by_user_id: str | None = None


class AutomationDetail(BaseModel):
    automation: Automation
    versions: list[AutomationVersion]


class AutomationRunCreate(BaseModel):
    profile_id: str | None = None


class AutomationRun(BaseModel):
    id: str
    automation_version_id: str
    profile_id: str | None = None
    status: str
    started_at: Any | None = None
    ended_at: Any | None = None
    log_text: str | None = None
    result_json: Any | None = None
    error_message: str | None = None
    triggered_by: str | None = None
    triggered_by_user_id: str | None = None


class AutomationRunQueued(BaseModel):
    run_id: str
    status: str


# ── Helpers ──────────────────────────────────────────────────────────────────


def _db():
    """Lazy import of :mod:`backend.db_automation`.

    Deferred so this router can be imported (and thus included in the
    FastAPI app) even when agent CC's branch hasn't merged yet. Endpoints
    that hit the DB will 500 with a clear error in that window.
    """
    from .. import db_automation  # noqa: WPS433 (intentional lazy import)

    return db_automation


def _resolve_workspace_for_request(
    request: Request, user: dict[str, Any], min_level: int
) -> str:
    """Pick the workspace for a list / create call and enforce ``min_level``.

    Same shape as :func:`backend.routers.proxies._resolve_workspace_for_request`:
    prefer the ``X-Workspace-Id`` header, else fall back to the user's
    first (oldest) workspace membership. 403 when the user has no
    workspaces at all.
    """
    requested = request.headers.get("x-workspace-id")
    if requested:
        check_role_for_workspace(user, requested, min_level)
        return requested

    workspaces = db_auth.list_workspaces_for_user(user["id"])
    if not workspaces:
        raise HTTPException(
            status_code=403,
            detail="User has no workspaces; cannot access automations",
        )
    ws_id = workspaces[0]["id"]
    check_role_for_workspace(user, ws_id, min_level)
    return ws_id


def _load_and_check_automation(
    automation_id: str, user: dict[str, Any], min_level: int
) -> dict[str, Any]:
    """Fetch an automation and enforce workspace membership + role level.

    404 hides existence across tenants (matches the rest of the API).
    """
    a = _db().get_automation(automation_id)
    if not a:
        raise HTTPException(status_code=404, detail="Automation not found")
    try:
        check_role_for_workspace(user, a.get("workspace_id"), min_level)
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404, detail="Automation not found"
            )
        raise
    return a


# ── Background run executor ──────────────────────────────────────────────────


async def _execute_run_async(
    run_id: str, version: dict[str, Any], profile_id: str | None
) -> None:
    """Fire-and-forget background task that drives a single run to terminal state.

    Writes ``status`` + ``log_text`` / ``result_json`` / ``error_message``
    via :mod:`backend.db_automation` so the row's final state is durable
    regardless of how this function exits. Exceptions are caught and
    serialised into ``error_message`` — we never let a background task
    crash the event loop.

    Wiring:
      * ``script`` kind is rejected with a clear error (out of scope for
        this phase).
      * For ``flow``: connect to the profile's CDP port via
        :func:`playwright.async_api.async_playwright().chromium.connect_over_cdp`,
        grab / create a page, hand it to :class:`FlowInterpreter`, and
        persist the resulting :class:`RunContext` state.
    """
    db = _db()
    try:
        db.mark_run_running(run_id)

        if version.get("kind") == "script":
            db.end_run(
                run_id,
                "failure",
                error_message="script mode not implemented yet",
            )
            return

        if not profile_id:
            db.end_run(
                run_id, "failure", error_message="profile_id required"
            )
            return

        running = browser_mgr.running.get(profile_id)
        if not running:
            db.end_run(
                run_id, "failure", error_message="profile not running"
            )
            return

        # Lazy import of Playwright + FlowInterpreter. Both are only
        # needed on the run path; the rest of the router (CRUD, listing)
        # must keep working even if Playwright isn't installed in this
        # environment yet.
        from playwright.async_api import async_playwright  # noqa: WPS433
        from ..automation import FlowInterpreter  # noqa: WPS433

        cdp_port = running.cdp_port
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(
                f"http://localhost:{cdp_port}"
            )
            ctx_browser = (
                browser.contexts[0] if browser.contexts else None
            )
            if ctx_browser is None:
                ctx_browser = await browser.new_context()
            page = (
                ctx_browser.pages[0]
                if ctx_browser.pages
                else await ctx_browser.new_page()
            )
            interpreter = FlowInterpreter(version.get("dsl_json"), page)
            result_ctx = await interpreter.run()
            db.end_run(
                run_id,
                "success",
                result_json=getattr(result_ctx, "variables", None),
                log_text="\n".join(
                    getattr(result_ctx, "log_lines", []) or []
                ),
            )
    except Exception as exc:  # background task — never propagate
        logger.exception("automation run %s failed", run_id)
        try:
            db.end_run(
                run_id, "failure", error_message=str(exc)[:500]
            )
        except Exception:  # last-ditch — DB is also down
            logger.exception(
                "automation run %s: failed to record terminal status",
                run_id,
            )


# ── Automation CRUD ──────────────────────────────────────────────────────────


@router.get("", response_model=list[Automation])
async def list_automations(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    ws_id = _resolve_workspace_for_request(
        request, user, ROLE_LEVEL["viewer"]
    )
    rows = _db().list_automations(ws_id)
    return [Automation(**r) for r in rows]


@router.post("", response_model=Automation, status_code=201)
async def create_automation(
    req: AutomationCreate,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    ws_id = _resolve_workspace_for_request(
        request, user, ROLE_LEVEL["editor"]
    )
    try:
        row = _db().create_automation(
            workspace_id=ws_id,
            name=req.name,
            kind=req.kind,
            description=req.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return Automation(**row)


@router.get("/{automation_id}", response_model=AutomationDetail)
async def get_automation(
    automation_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    a = _load_and_check_automation(
        automation_id, user, ROLE_LEVEL["viewer"]
    )
    versions = _db().list_versions(automation_id)
    return AutomationDetail(
        automation=Automation(**a),
        versions=[AutomationVersion(**v) for v in versions],
    )


@router.put("/{automation_id}", response_model=Automation)
async def update_automation(
    automation_id: str,
    req: AutomationUpdate,
    user: dict[str, Any] = Depends(get_current_user),
):
    _load_and_check_automation(automation_id, user, ROLE_LEVEL["editor"])
    fields = req.model_dump(exclude_unset=True)
    if not fields:
        # Nothing to update — just return the current row.
        row = _db().get_automation(automation_id)
        return Automation(**row)
    try:
        row = _db().update_automation(automation_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if row is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    return Automation(**row)


@router.delete("/{automation_id}", status_code=204)
async def delete_automation(
    automation_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    _load_and_check_automation(automation_id, user, ROLE_LEVEL["editor"])
    _db().delete_automation(automation_id)
    return Response(status_code=204)


# ── Versions ─────────────────────────────────────────────────────────────────


@router.post(
    "/{automation_id}/versions",
    response_model=AutomationVersion,
    status_code=201,
)
async def create_version(
    automation_id: str,
    req: AutomationVersionCreate,
    user: dict[str, Any] = Depends(get_current_user),
):
    a = _load_and_check_automation(
        automation_id, user, ROLE_LEVEL["editor"]
    )
    kind = a["kind"]

    # Shape validation lives in the router so the DB layer stays dumb
    # about the kind→fields mapping (which is a product-level rule, not
    # a schema-level one — both columns are nullable at the table level).
    if kind == "flow":
        if req.dsl_json is None:
            raise HTTPException(
                status_code=400,
                detail="dsl_json is required for flow automations",
            )
    elif kind == "script":
        if not req.script_code or not req.script_language:
            raise HTTPException(
                status_code=400,
                detail=(
                    "script_code and script_language are required for "
                    "script automations"
                ),
            )
    else:  # defensive — DB layer should have rejected unknown kinds
        raise HTTPException(
            status_code=400, detail=f"unknown automation kind: {kind}"
        )

    try:
        row = _db().create_version(
            automation_id=automation_id,
            kind=kind,
            dsl_json=req.dsl_json,
            script_language=req.script_language,
            script_code=req.script_code,
            created_by_user_id=user.get("id"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return AutomationVersion(**row)


# ── Runs ─────────────────────────────────────────────────────────────────────


@router.get(
    "/{automation_id}/runs", response_model=list[AutomationRun]
)
async def list_runs(
    automation_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: dict[str, Any] = Depends(get_current_user),
):
    _load_and_check_automation(automation_id, user, ROLE_LEVEL["viewer"])
    rows = _db().list_runs(
        automation_id=automation_id, limit=limit, offset=offset
    )
    return [AutomationRun(**r) for r in rows]


@router.post(
    "/{automation_id}/run",
    response_model=AutomationRunQueued,
    status_code=202,
)
async def trigger_run(
    automation_id: str,
    req: AutomationRunCreate,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Queue a run of the automation's latest version against a profile.

    Authorization:
      * launcher+ in the automation's workspace.
      * If ``profile_id`` is set, launcher+ in the profile's workspace too
        (cross-workspace launches are rejected with 404 to avoid leaking
        profile existence — same pattern as profiles.py).

    Execution is fire-and-forget: we insert a ``queued`` row, schedule a
    background task, and return ``202`` immediately. The task transitions
    the row to ``running`` then to ``success`` / ``failure`` when done.
    """
    a = _load_and_check_automation(
        automation_id, user, ROLE_LEVEL["launcher"]
    )

    # Cross-workspace profile guard. We deliberately use the local
    # `database` module rather than db_automation so this works the
    # moment a profile row exists, independent of CC's branch state.
    profile_id = req.profile_id
    if profile_id:
        from .. import database as db  # noqa: WPS433

        profile = db.get_profile(profile_id)
        if not profile:
            raise HTTPException(
                status_code=404, detail="Profile not found"
            )
        profile_ws = profile.get("workspace_id")
        try:
            check_role_for_workspace(
                user, profile_ws, ROLE_LEVEL["launcher"]
            )
        except HTTPException as exc:
            if exc.status_code == 404:
                raise HTTPException(
                    status_code=404, detail="Profile not found"
                )
            raise

    latest_version_id = a.get("latest_version_id")
    if not latest_version_id:
        raise HTTPException(
            status_code=400,
            detail="automation has no versions yet; create one first",
        )
    version = _db().get_version(latest_version_id)
    if not version:
        # Stale pointer — shouldn't happen given the FK, but stay defensive.
        raise HTTPException(
            status_code=400,
            detail="latest version is missing; create a new one",
        )

    run = _db().create_run(
        automation_version_id=latest_version_id,
        profile_id=profile_id,
        triggered_by="manual",
        triggered_by_user_id=user.get("id"),
    )
    run_id = run["id"]

    # Background task — never awaited by the request. We don't store the
    # task handle: Python keeps a strong ref via the running event loop,
    # and the function catches every exception itself.
    asyncio.create_task(_execute_run_async(run_id, version, profile_id))

    return AutomationRunQueued(run_id=run_id, status=run.get("status", "queued"))


# ── Single run lookup ────────────────────────────────────────────────────────
#
# Mounted on a separate sub-path because the run id alone is the natural
# key — clients shouldn't have to remember which automation it came from.
# Sharing the same router keeps the include_router call in main.py to a
# single line per the task constraints.


@router.get("/runs/{run_id}", response_model=AutomationRun)
async def get_run(
    run_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Fetch a single run row.

    Walks run → version → automation to find the workspace, then enforces
    viewer+ on that workspace. 404 across tenants per the project-wide
    leakage policy.
    """
    db = _db()
    run = db.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    version = db.get_version(run["automation_version_id"])
    if not version:
        raise HTTPException(status_code=404, detail="Run not found")
    automation = db.get_automation(version["automation_id"])
    if not automation:
        raise HTTPException(status_code=404, detail="Run not found")

    try:
        check_role_for_workspace(
            user, automation.get("workspace_id"), ROLE_LEVEL["viewer"]
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail="Run not found")
        raise

    return AutomationRun(**run)


# ── Schedules ────────────────────────────────────────────────────────────────
#
# Cron schedule CRUD. The reconcile loop in
# :mod:`backend.automation_scheduler` computes ``next_fire_at`` shortly
# after rows are inserted/updated, so endpoints here only own the static
# fields (cron / timezone / enabled / profile_id).
#
# Authz: viewer+ to list, editor+ to mutate — same floor as automation
# CRUD. Routes accepting ``{schedule_id}`` resolve the parent automation
# first so we can use the existing ``_load_and_check_automation`` to
# enforce workspace membership and hide cross-tenant existence behind 404.
#
# Cron expressions are validated with ``croniter`` (already a backend
# dependency for the scheduler worker). The import is deferred so the
# rest of the router keeps loading if croniter goes missing in some env.


def _validate_cron_or_400(cron: str) -> None:
    try:
        from croniter import croniter as _ct  # noqa: WPS433
        _ct(cron)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cron expression")


@router.get(
    "/{automation_id}/schedules", response_model=list[Schedule]
)
def list_schedules_route(
    automation_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    _load_and_check_automation(automation_id, user, ROLE_LEVEL["viewer"])
    rows = _db().list_schedules(automation_id=automation_id)
    return [Schedule(**r) for r in rows]


@router.post(
    "/{automation_id}/schedules",
    status_code=201,
    response_model=Schedule,
)
def create_schedule_route(
    automation_id: str,
    body: ScheduleCreate,
    user: dict[str, Any] = Depends(get_current_user),
):
    _load_and_check_automation(automation_id, user, ROLE_LEVEL["editor"])
    _validate_cron_or_400(body.cron)
    row = _db().create_schedule(
        automation_id=automation_id,
        cron=body.cron,
        profile_id=body.profile_id,
        timezone=body.timezone,
        enabled=body.enabled,
    )
    return Schedule(**row)


@router.put("/schedules/{schedule_id}", response_model=Schedule)
def update_schedule_route(
    schedule_id: str,
    body: ScheduleUpdate,
    user: dict[str, Any] = Depends(get_current_user),
):
    s = _db().get_schedule(schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    _load_and_check_automation(
        s["automation_id"], user, ROLE_LEVEL["editor"]
    )
    if body.cron:
        _validate_cron_or_400(body.cron)
    updated = _db().update_schedule(
        schedule_id, **body.model_dump(exclude_unset=True)
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return Schedule(**updated)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule_route(
    schedule_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    s = _db().get_schedule(schedule_id)
    if not s:
        raise HTTPException(status_code=404, detail="Schedule not found")
    _load_and_check_automation(
        s["automation_id"], user, ROLE_LEVEL["editor"]
    )
    _db().delete_schedule(schedule_id)
    return Response(status_code=204)
