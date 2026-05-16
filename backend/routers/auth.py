"""Authentication endpoints: status, login, logout."""

from __future__ import annotations

import hmac

import starlette.requests
from fastapi import APIRouter, HTTPException, Request, Response

from ..dependencies import _is_https
from ..models import LoginRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
async def auth_status(request: starlette.requests.Request):
    """Check if auth is enabled and if the current request is authenticated.

    Exempt from auth middleware so the frontend can always call it.
    """
    # Imported lazily to honour test monkeypatches on ``main.AUTH_TOKEN``.
    from .. import main as _main

    authenticated = False
    if _main.AUTH_TOKEN:
        authenticated = _main._check_auth(request.scope)
    return {"auth_required": _main.AUTH_TOKEN is not None, "authenticated": authenticated}


@router.post("/login")
async def auth_login(body: LoginRequest, request: Request, response: Response):
    from .. import main as _main

    if not _main.AUTH_TOKEN:
        return {"ok": True}
    if not body.token or not hmac.compare_digest(body.token, _main.AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid token")
    is_https = _is_https(request)
    response.set_cookie(
        key="auth_token",
        value=_main.AUTH_TOKEN,
        httponly=True,
        samesite="strict",
        secure=is_https,
        path="/",
    )
    return {"ok": True}


@router.post("/logout")
async def auth_logout(request: Request, response: Response):
    is_https = _is_https(request)
    response.delete_cookie(
        key="auth_token", path="/", secure=is_https, samesite="strict",
    )
    return {"ok": True}
