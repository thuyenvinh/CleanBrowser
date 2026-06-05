"""Clipboard relay endpoints (set/get the VNC session's X clipboard).

Workspace-scoped: the caller must be a member of the profile's workspace
with at least ``launcher`` role. Without this, anyone who knew a profile
id could read or inject text into another tenant's running browser
session (security review finding C-02).
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import database as db
from ..dependencies import (
    ROLE_LEVEL,
    browser_mgr,
    check_role_for_workspace,
    get_current_user,
)
from ..models import ClipboardRequest
from ..rate_limit import limiter

logger = logging.getLogger("cloakbrowser.manager")

router = APIRouter(prefix="/api/profiles", tags=["clipboard"])

_CLIPBOARD_MAX_READ = 1_048_576  # 1MB cap on GET response

# Track xclip processes per display so we can kill the old one before spawning new
_xclip_procs: dict[int, asyncio.subprocess.Process] = {}


def _authorize_profile(profile_id: str, user: dict | None) -> None:
    """Resolve profile + enforce ``launcher`` role on its workspace.

    Returns 404 when the user isn't a workspace member, matching the
    leak-avoidance convention used by the rest of the multi-tenant layer.
    """
    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    check_role_for_workspace(user, profile.get("workspace_id"), ROLE_LEVEL["launcher"])


@router.post("/{profile_id}/clipboard")
@limiter.limit("60/minute")
async def set_clipboard(
    profile_id: str,
    body: ClipboardRequest,
    request: Request,  # noqa: ARG001 — required by the rate limiter
    user: dict = Depends(get_current_user),
):
    """Push text into the VNC session's X clipboard via xclip."""
    _authorize_profile(profile_id, user)
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")

    import os

    # Imported lazily so tests can patch ``backend.main.asyncio.create_subprocess_exec``.
    from .. import main as _main

    # Kill previous xclip for this display (it stays alive to serve paste)
    old = _xclip_procs.pop(running.display, None)
    if old and old.returncode is None:
        old.kill()
        await old.wait()

    env = {**os.environ, "DISPLAY": f":{running.display}"}
    proc = await _main.asyncio.create_subprocess_exec(
        "xclip", "-selection", "clipboard",
        stdin=asyncio.subprocess.PIPE,
        env=env,
    )
    # xclip reads stdin then stays alive to serve paste requests.
    proc.stdin.write(body.text.encode())  # type: ignore[union-attr]
    await proc.stdin.drain()  # type: ignore[union-attr]
    proc.stdin.close()  # type: ignore[union-attr]

    _xclip_procs[running.display] = proc

    return {"ok": True}


@router.get("/{profile_id}/clipboard")
@limiter.limit("120/minute")
async def get_clipboard(
    profile_id: str,
    request: Request,  # noqa: ARG001 — required by the rate limiter
    user: dict = Depends(get_current_user),
):
    """Read the VNC session's clipboard.

    Chrome doesn't write to X11 clipboard under KasmVNC, so xclip can't read it.
    Instead, read via Playwright's CDP connection to Chrome (navigator.clipboard.readText).
    Falls back to xclip for non-Chrome clipboard owners.
    """
    _authorize_profile(profile_id, user)
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")

    # Read Chrome's current text selection via Playwright.
    # Chrome's native copy (via VNC Ctrl+C) doesn't write to X11 clipboard
    # and doesn't fire DOM events, so we read the visible selection instead.
    # The init script also captures copy events when they do fire.
    # Check all pages — user may have copied in any tab
    try:
        for page in running.context.pages:
            try:
                text = await page.evaluate("window.__clipboardText || ''")
                if text:
                    return {"text": text[:_CLIPBOARD_MAX_READ]}
            except Exception as exc:
                logger.debug("Clipboard read failed on page: %s", exc)
                continue
    except Exception as exc:
        logger.debug("Playwright clipboard read failed: %s", exc)

    # Fallback: xclip for non-Chrome clipboard owners
    import os

    env = {**os.environ, "DISPLAY": f":{running.display}"}
    proc = await asyncio.create_subprocess_exec(
        "xclip", "-selection", "clipboard", "-o",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {"text": ""}

    if proc.returncode != 0:
        return {"text": ""}

    text = stdout[:_CLIPBOARD_MAX_READ].decode("utf-8", errors="replace")
    return {"text": text}
