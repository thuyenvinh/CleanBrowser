"""CDP HTTP info + WebSocket proxy endpoints.

Simple bidirectional passthrough — CDP is standard JSON over WebSocket,
no protocol translation needed (unlike VNC which requires RFB filtering).
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from .. import database as db
from .. import db_auth
from ..auth_tokens import decode_session
from ..dependencies import (
    ROLE_LEVEL,
    SESSION_COOKIE,
    _check_websocket_origin,
    _is_https,
    browser_mgr,
    check_role_for_workspace,
    get_optional_user,
)

logger = logging.getLogger("cloakbrowser.manager")

router = APIRouter(prefix="/api/profiles", tags=["cdp"])


def _enforce_cdp_role(profile_id: str, user: dict | None, min_level: int) -> None:
    """Pre-flight RBAC check for HTTP CDP endpoints.

    Mirrors ``routers/profiles._load_and_check``: resolves the profile, returns
    404 when it doesn't exist or the authenticated user isn't a member of its
    workspace, 403 when membership exists but the role is below ``min_level``.
    Anonymous / legacy AUTH_TOKEN callers (``user is None``) bypass the role
    check, matching the rest of the multi-tenant layering.
    """
    profile = db.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    check_role_for_workspace(user, profile.get("workspace_id"), min_level)


async def _authorize_ws_for_profile(
    websocket: WebSocket, profile_id: str, min_level: int
) -> dict | None:
    """Pre-handshake role check for a profile-scoped WebSocket endpoint.

    See ``routers/vnc._authorize_ws_for_profile`` for the full contract — this
    is an intentional duplicate scoped to CDP so we don't widen the public
    surface of ``dependencies``.
    """
    token = websocket.cookies.get(SESSION_COOKIE)
    user = None
    if token:
        claims = decode_session(token)
        if claims and claims.get("sub"):
            try:
                candidate = db_auth.get_user(claims["sub"])
            except Exception:
                logger.exception(
                    "_authorize_ws_for_profile: db lookup failed for sub=%s",
                    claims.get("sub"),
                )
                candidate = None
            if candidate and candidate.get("status") == "active":
                if not claims.get("tid") or claims["tid"] == candidate.get("tenant_id"):
                    user = candidate

    profile = db.get_profile(profile_id)
    if not profile:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return None

    if user is not None:
        ws_id = profile.get("workspace_id")
        if not ws_id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None
        try:
            role = db_auth.get_member_role(ws_id, user["id"])
        except Exception:
            logger.exception(
                "_authorize_ws_for_profile: get_member_role failed (ws=%s user=%s)",
                ws_id,
                user.get("id"),
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None
        if not role or ROLE_LEVEL.get(role, 0) < min_level:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return None

    return profile


@router.get("/{profile_id}/cdp")
async def cdp_info(
    profile_id: str,
    user: dict | None = Depends(get_optional_user),
):
    """Return CDP connection info. Prevents SPA catch-all from serving index.html."""
    _enforce_cdp_role(profile_id, user, ROLE_LEVEL["launcher"])
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")
    return {
        "cdp_url": f"/api/profiles/{profile_id}/cdp",
        "usage": "playwright.chromium.connect_over_cdp('http://<host>/api/profiles/"
        + profile_id + "/cdp')",
    }


@router.get("/{profile_id}/cdp/json/version/")
@router.get("/{profile_id}/cdp/json/version")
async def cdp_json_version(
    profile_id: str,
    request: Request,
    user: dict | None = Depends(get_optional_user),
):
    """Proxy Chrome's /json/version, rewriting WS URLs to go through our proxy."""
    _enforce_cdp_role(profile_id, user, ROLE_LEVEL["launcher"])
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{running.cdp_port}/json/version", timeout=5
            )
            data = resp.json()
    except Exception as exc:
        logger.error("CDP proxy: failed to reach Chrome CDP for %s: %s", profile_id, exc)
        raise HTTPException(status_code=502, detail="CDP endpoint unreachable")

    # Rewrite webSocketDebuggerUrl to point through our proxy
    host = request.headers.get("host", "localhost:8080")
    ws_scheme = "wss" if _is_https(request) else "ws"
    data["webSocketDebuggerUrl"] = f"{ws_scheme}://{host}/api/profiles/{profile_id}/cdp"
    return data


@router.get("/{profile_id}/cdp/json/list/")
@router.get("/{profile_id}/cdp/json/list")
@router.get("/{profile_id}/cdp/json/")
@router.get("/{profile_id}/cdp/json")
async def cdp_json_list(
    profile_id: str,
    request: Request,
    user: dict | None = Depends(get_optional_user),
):
    """Proxy Chrome's /json/list, rewriting WS URLs."""
    _enforce_cdp_role(profile_id, user, ROLE_LEVEL["launcher"])
    running = browser_mgr.running.get(profile_id)
    if not running:
        raise HTTPException(status_code=404, detail="Profile not running")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{running.cdp_port}/json/list", timeout=5
            )
            data = resp.json()
    except Exception as exc:
        logger.error("CDP proxy: failed to reach Chrome CDP for %s: %s", profile_id, exc)
        raise HTTPException(status_code=502, detail="CDP endpoint unreachable")

    host = request.headers.get("host", "localhost:8080")
    ws_scheme = "wss" if _is_https(request) else "ws"
    for entry in data:
        if "webSocketDebuggerUrl" in entry:
            ws_path = entry["webSocketDebuggerUrl"].split("/devtools/")[-1]
            entry["webSocketDebuggerUrl"] = (
                f"{ws_scheme}://{host}/api/profiles/{profile_id}/cdp/devtools/{ws_path}"
            )
    return data


async def _proxy_cdp_websocket(
    websocket: WebSocket, target_url: str, label: str,
) -> None:
    """Bidirectional WebSocket proxy between a FastAPI client and a CDP target.

    Used by both browser-level and page-level CDP proxy endpoints.
    """
    import websockets

    try:
        async with websockets.connect(
            target_url, max_size=None, ping_interval=None, ping_timeout=None
        ) as cdp_ws:
            logger.info("%s: connected to %s", label, target_url)

            async def client_to_cdp():
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("type") == "websocket.disconnect":
                            break
                        if "text" in msg and msg["text"]:
                            await cdp_ws.send(msg["text"])
                        elif "bytes" in msg and msg["bytes"]:
                            await cdp_ws.send(msg["bytes"])
                except WebSocketDisconnect:
                    pass
                except Exception as exc:
                    logger.warning("%s [c->cdp]: %s: %s", label, type(exc).__name__, exc)

            async def cdp_to_client():
                try:
                    async for msg in cdp_ws:
                        if isinstance(msg, str):
                            await websocket.send_text(msg)
                        else:
                            await websocket.send_bytes(msg)
                except WebSocketDisconnect:
                    pass
                except Exception as exc:
                    logger.warning("%s [cdp->c]: %s: %s", label, type(exc).__name__, exc)

            c2d = asyncio.create_task(client_to_cdp(), name="c2d")
            d2c = asyncio.create_task(cdp_to_client(), name="d2c")
            done, pending = await asyncio.wait(
                [c2d, d2c], return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            logger.info("%s: disconnected", label)

    except Exception as exc:
        logger.error("%s error: %s", label, exc)
    finally:
        try:
            await websocket.close()
        except Exception as exc:
            logger.debug("%s: websocket.close() failed: %s", label, exc)


@router.websocket("/{profile_id}/cdp")
async def cdp_proxy(websocket: WebSocket, profile_id: str):
    """Proxy WebSocket frames between external tools and Chrome's CDP."""
    if not await _check_websocket_origin(websocket):
        return

    # Pre-handshake RBAC: CDP access requires launcher+ role.
    if await _authorize_ws_for_profile(websocket, profile_id, min_level=ROLE_LEVEL["launcher"]) is None:
        return

    running = browser_mgr.running.get(profile_id)
    if not running:
        await websocket.close(code=4004, reason="Profile not running")
        return

    await websocket.accept()

    # Get browser-level CDP WebSocket URL from Chrome
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"http://127.0.0.1:{running.cdp_port}/json/version", timeout=5
            )
            ws_url = resp.json()["webSocketDebuggerUrl"]
    except Exception as exc:
        logger.error("CDP proxy: failed to get WS URL for %s: %s", profile_id, exc)
        await websocket.close(code=4005, reason="CDP not available")
        return

    await _proxy_cdp_websocket(websocket, ws_url, f"CDP proxy [{profile_id}]")


@router.websocket("/{profile_id}/cdp/devtools/{path:path}")
async def cdp_page_proxy(websocket: WebSocket, profile_id: str, path: str):
    """Proxy page-specific CDP WebSocket connections (e.g. /devtools/page/GUID)."""
    if not await _check_websocket_origin(websocket):
        return

    # Pre-handshake RBAC: CDP access requires launcher+ role.
    if await _authorize_ws_for_profile(websocket, profile_id, min_level=ROLE_LEVEL["launcher"]) is None:
        return

    running = browser_mgr.running.get(profile_id)
    if not running:
        await websocket.close(code=4004, reason="Profile not running")
        return

    await websocket.accept()

    target_url = f"ws://127.0.0.1:{running.cdp_port}/devtools/{path}"
    await _proxy_cdp_websocket(websocket, target_url, f"CDP page proxy [{profile_id}]")
