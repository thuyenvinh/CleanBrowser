"""Authentication endpoints.

Two coexisting auth modes during the Phase 1 → Phase 2 transition:

* **Legacy single-token auth** (``AUTH_TOKEN`` env var). When set, every API
  call needs an ``Authorization: Bearer <token>`` header or matching
  ``auth_token`` cookie. The ``AuthMiddleware`` in :mod:`backend.main` enforces
  this; the ``/api/auth/status`` + ``/api/auth/login`` endpoints below speak
  the legacy ``{token: ...}`` payload.

* **Multi-tenant JWT session** (Wave 2 onward). Users sign up / log in via
  email + password; the server issues a 24h HS256 JWT in an httpOnly
  ``session`` cookie. Routes opt in by depending on
  :func:`backend.dependencies.get_current_user`.

The two modes coexist deliberately — tests and existing single-tenant
deployments must keep working while the new flow comes online.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Any

import starlette.requests
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import ValidationError

from .. import db_auth
from ..auth_tokens import JWT_LIFETIME_SECONDS, encode_session
from ..dependencies import SESSION_COOKIE, _is_https, get_current_user
from ..models import (
    EmailLoginRequest,
    LoginRequest,
    MfaDisableRequest,
    MfaEnableRequest,
    MfaSetupResponse,
    SignupRequest,
    UserPublic,
    Workspace,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

logger = logging.getLogger("cloakbrowser.auth")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cookie_secure() -> bool:
    """Whether to set ``Secure`` on auth cookies (env-controlled, default off)."""
    return os.environ.get("COOKIE_SECURE", "false").lower() == "true"


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=JWT_LIFETIME_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path="/",
        samesite="lax",
        secure=_cookie_secure(),
    )


def _user_public(user_row: dict[str, Any]) -> dict[str, Any]:
    """Project a user DB row to the public-safe shape (no password_hash)."""
    return UserPublic(
        id=user_row["id"],
        tenant_id=user_row["tenant_id"],
        email=user_row["email"],
        status=user_row.get("status", "active"),
        created_at=user_row["created_at"],
    ).model_dump()


def _workspace_public(ws_row: dict[str, Any]) -> dict[str, Any]:
    return Workspace(
        id=ws_row["id"],
        tenant_id=ws_row["tenant_id"],
        name=ws_row["name"],
        owner_user_id=ws_row["owner_user_id"],
        created_at=ws_row["created_at"],
    ).model_dump()


def _auth_payload(user_row: dict[str, Any]) -> dict[str, Any]:
    workspaces = db_auth.list_workspaces_for_user(user_row["id"])
    return {
        "user": _user_public(user_row),
        "workspaces": [_workspace_public(w) for w in workspaces],
    }


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


@router.get("/status")
async def auth_status(request: starlette.requests.Request):
    """Report whether auth is required and whether the caller is authenticated.

    Exempt from the legacy auth middleware so the frontend can always call it.
    A caller is considered ``authenticated`` if *either* the legacy
    ``AUTH_TOKEN`` is presented (header/cookie) *or* a valid JWT ``session``
    cookie is present.
    """
    from .. import main as _main

    authenticated = False
    user_public: dict[str, Any] | None = None

    # 1) JWT session cookie path — works regardless of AUTH_TOKEN.
    from ..dependencies import get_optional_user

    user = get_optional_user(request)  # type: ignore[arg-type]
    if user is not None:
        authenticated = True
        user_public = _user_public(user)

    # 2) Legacy token path — only meaningful when AUTH_TOKEN is configured.
    if not authenticated and _main.AUTH_TOKEN:
        authenticated = _main._check_auth(request.scope)

    return {
        "auth_required": _main.AUTH_TOKEN is not None,
        "authenticated": authenticated,
        "user": user_public,
    }


# ---------------------------------------------------------------------------
# Signup
# ---------------------------------------------------------------------------


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def auth_signup(body: SignupRequest, response: Response):
    existing = db_auth.get_user_by_email(body.email)
    if existing is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    try:
        _tenant, user, _workspace = db_auth.signup(
            email=body.email,
            password=body.password,
            tenant_name=body.tenant_name,
        )
    except Exception:
        logger.exception("signup failed for email=%s", body.email)
        raise HTTPException(status_code=500, detail="signup failed")

    token = encode_session(user["id"], user["tenant_id"])
    _set_session_cookie(response, token)
    return _auth_payload(user)


# ---------------------------------------------------------------------------
# Login (dual-mode: email+password OR legacy {token})
# ---------------------------------------------------------------------------


@router.post("/login")
async def auth_login(request: Request, response: Response):
    """Login handler.

    Accepts either:
      * ``{email, password}`` — multi-tenant flow, issues a JWT session cookie.
      * ``{token}``           — legacy single-token flow (compat with
        ``AUTH_TOKEN`` deployments and the existing test suite).

    Dispatched on the JSON body shape so a single endpoint serves both
    frontends.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = None

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="invalid JSON body")

    # ── Email/password path ─────────────────────────────────────────────────
    if "email" in payload or "password" in payload:
        try:
            body = EmailLoginRequest.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors())

        user = db_auth.get_user_by_email(body.email)
        # Generic 401 — never leak whether the email exists.
        if user is None or not db_auth.verify_password(
            body.password, user["password_hash"]
        ):
            raise HTTPException(status_code=401, detail="invalid credentials")
        if user.get("status") != "active":
            raise HTTPException(status_code=401, detail="invalid credentials")

        # MFA challenge: if the user has a stored secret, require a valid OTP
        # before issuing the session cookie. We intentionally do NOT cap retries
        # here — the TOTP window itself + rate limiting upstream is the defence.
        if user.get("mfa_secret"):
            if not body.code:
                # First leg: client doesn't know MFA is on. Tell them, no cookie.
                return {"mfa_required": True}
            if not db_auth.verify_totp(user["id"], body.code):
                raise HTTPException(status_code=401, detail="invalid mfa code")

        token = encode_session(user["id"], user["tenant_id"])
        _set_session_cookie(response, token)
        return _auth_payload(user)

    # ── Legacy token path ───────────────────────────────────────────────────
    from .. import main as _main

    try:
        body = LoginRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

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


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------


@router.post("/logout")
async def auth_logout(request: Request, response: Response):
    """Clear both the JWT session cookie and the legacy auth_token cookie.

    Returns ``204 No Content`` when called by a multi-tenant client (has a
    ``session`` cookie) and ``{ok: true}`` otherwise — preserving the legacy
    test contract while satisfying ``frontend/src/lib/auth.ts`` which expects
    a 204.
    """
    had_session = request.cookies.get(SESSION_COOKIE) is not None

    if had_session:
        # Build a fresh 204 response so the body is empty; attach Set-Cookie
        # headers directly so the cookies still get cleared client-side.
        resp = Response(status_code=status.HTTP_204_NO_CONTENT)
        resp.delete_cookie(
            key=SESSION_COOKIE,
            path="/",
            samesite="lax",
            secure=_cookie_secure(),
        )
        resp.delete_cookie(
            key="auth_token",
            path="/",
            samesite="strict",
            secure=_is_https(request),
        )
        return resp

    _clear_session_cookie(response)
    response.delete_cookie(
        key="auth_token", path="/", secure=_is_https(request), samesite="strict",
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------


@router.get("/me")
async def auth_me(user: dict[str, Any] = Depends(get_current_user)):
    return _auth_payload(user)


# ---------------------------------------------------------------------------
# MFA (TOTP) — optional second factor
#
# Flow:
#   1. Client POST /mfa/setup → server returns a freshly generated secret +
#      otpauth:// provisioning URI. Nothing is persisted yet.
#   2. Client renders the QR code, user scans it with their authenticator,
#      enters the first 6-digit code.
#   3. Client POST /mfa/enable with {secret, code}. If the code validates
#      against the secret, the secret is persisted on the user row.
#   4. From the next /login onward, the user must supply ``code`` to complete
#      authentication. See the JSON branch of ``auth_login`` above.
#
# We intentionally avoid server-side session storage of the in-progress secret:
# bouncing it through the client is the standard pattern and means /setup is
# idempotent / stateless. The secret only becomes authoritative once /enable
# accepts a proof-of-possession code.
# ---------------------------------------------------------------------------


@router.post("/mfa/setup", response_model=MfaSetupResponse)
async def auth_mfa_setup(user: dict[str, Any] = Depends(get_current_user)):
    import pyotp

    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(
        name=user["email"], issuer_name="CleanBrowser"
    )
    return MfaSetupResponse(secret=secret, qr_provisioning_uri=uri)


@router.post("/mfa/enable")
async def auth_mfa_enable(
    body: MfaEnableRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    import pyotp

    try:
        ok = pyotp.TOTP(body.secret).verify(body.code, valid_window=1)
    except Exception:
        ok = False
    if not ok:
        raise HTTPException(status_code=400, detail="invalid mfa code")

    db_auth.enable_mfa(user["id"], body.secret)
    return {"enabled": True}


@router.post("/mfa/disable")
async def auth_mfa_disable(
    body: MfaDisableRequest,
    user: dict[str, Any] = Depends(get_current_user),
):
    # Double-check: require both the current password AND a valid OTP. Either
    # alone would lower the bar for an attacker who has only one factor (e.g.
    # a hijacked session + leaked password, or stolen device + session).
    if not db_auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="invalid credentials")
    if not db_auth.verify_totp(user["id"], body.code):
        raise HTTPException(status_code=401, detail="invalid mfa code")

    db_auth.disable_mfa(user["id"])
    return {"enabled": False}
