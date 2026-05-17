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

from .. import db_auth, email_sender
from ..auth_tokens import JWT_LIFETIME_SECONDS, encode_session
from ..dependencies import SESSION_COOKIE, _is_https, get_current_user
from ..rate_limit import limiter
from ..models import (
    EmailLoginRequest,
    LoginRequest,
    MfaDisableRequest,
    MfaEnableRequest,
    MfaSetupResponse,
    ResendVerificationResponse,
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
        email_verified_at=user_row.get("email_verified_at"),
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
@limiter.limit("5/hour")
async def auth_signup(
    request: Request, body: SignupRequest, response: Response
):
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

    # Fire-and-forget verification email. A broken mailer must not block
    # signup itself — the user can always trigger a resend from the banner.
    try:
        _, verify_token = db_auth.create_email_verification_token(user["id"])
        verify_url = (
            str(request.url_for("verify_email_get")) + f"?token={verify_token}"
        )
        email_sender.send_verification_email(user["email"], verify_url)
    except Exception:
        logger.exception(
            "failed to send verification email for user=%s", user["id"]
        )

    token = encode_session(user["id"], user["tenant_id"])
    _set_session_cookie(response, token)
    return _auth_payload(user)


# ---------------------------------------------------------------------------
# Login (dual-mode: email+password OR legacy {token})
# ---------------------------------------------------------------------------


@router.post("/login")
@limiter.limit("10/minute")
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
@limiter.limit("5/minute")
async def auth_mfa_enable(
    request: Request,
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
@limiter.limit("5/minute")
async def auth_mfa_disable(
    request: Request,
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


# ---------------------------------------------------------------------------
# Email verification
#
# Flow (see also ``backend/email_sender.py`` and migration 0011):
#   1. Signup mints a 256-bit URL-safe token, stores only its SHA-256, and
#      emails the plaintext as a link to GET /api/auth/verify-email.
#   2. The user clicks the link; we consume the token (one-shot, 24h TTL),
#      flip ``users.email_verified_at``, and redirect them to ``/?verified=1``
#      so the SPA can drop its "please verify" banner.
#   3. The banner can also POST /api/auth/resend-verification, which mints a
#      fresh token and emails it again. We never reveal "already verified"
#      via the verify endpoint (any consumed/expired/unknown token gets the
#      same generic error) but we *do* tell the authenticated resend caller
#      so the banner can stop nagging.
# ---------------------------------------------------------------------------


@router.get("/verify-email", name="verify_email_get")
async def verify_email_get(token: str):
    from fastapi.responses import HTMLResponse, RedirectResponse

    user_id = db_auth.consume_email_verification_token(token)
    if not user_id:
        return HTMLResponse(
            "<h1>Invalid or expired verification link</h1>"
            "<p>Please request a new verification email from the app.</p>",
            status_code=400,
        )
    db_auth.set_email_verified(user_id)
    # Redirect to the SPA root with a query flag the frontend can pick up to
    # show a transient success toast; the SPA will also notice the missing
    # ``email_verified_at`` after a fresh /api/auth/me round-trip.
    return RedirectResponse("/?verified=1", status_code=302)


@router.post("/resend-verification", response_model=ResendVerificationResponse)
@limiter.limit("3/hour")
async def resend_verification(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
):
    if user.get("email_verified_at"):
        return ResendVerificationResponse(already_verified=True)
    _, verify_token = db_auth.create_email_verification_token(user["id"])
    verify_url = (
        str(request.url_for("verify_email_get")) + f"?token={verify_token}"
    )
    sent = email_sender.send_verification_email(user["email"], verify_url)
    return ResendVerificationResponse(sent=sent)


# ---------------------------------------------------------------------------
# OAuth login (Phase 1 task WW — Google + GitHub)
#
# Three endpoints implement the classic Authorization Code dance:
#
#   GET /oauth/{provider}/start
#       Mints an anti-CSRF ``state`` token, stashes it in a short-lived
#       httpOnly cookie, and 302-redirects the user-agent to the IdP's
#       consent screen with our ``redirect_uri`` baked in.
#
#   GET /oauth/{provider}/callback
#       The IdP redirects the user-agent here with ``code`` + ``state``.
#       We compare ``state`` against the cookie (CSRF defence — without it
#       an attacker could trick a logged-in victim into binding the
#       attacker's IdP identity to the victim's app account), exchange the
#       code for an access token, fetch the user profile, and resolve the
#       OAuth identity to a local user:
#         * existing OAuth link  → log in
#         * email already taken  → link OAuth + log in
#         * fresh email          → signup_oauth + log in
#       Then issue the same JWT session cookie ``/login`` does and 302
#       back to the SPA root.
#
#   GET /oauth/providers
#       Tells the SPA which providers are configured so it can hide the
#       buttons that would fail at ``/start``.
#
# Why no PKCE: both endpoints we redirect to (``/start``, ``/callback``)
# are server-side and confidential — the client secret is enough. PKCE
# only becomes essential when a public client (SPA/mobile) holds the code
# verifier, which is not this Phase 1 flow.
# ---------------------------------------------------------------------------


_OAUTH_STATE_COOKIE = "cb_oauth_state"
_OAUTH_STATE_TTL_SECONDS = 600  # 10 minutes — covers slow IdP screens.


def _set_oauth_state_cookie(response: Response, state: str) -> None:
    response.set_cookie(
        key=_OAUTH_STATE_COOKIE,
        value=state,
        max_age=_OAUTH_STATE_TTL_SECONDS,
        httponly=True,
        # ``lax`` is required because the IdP performs a top-level GET
        # redirect back to us — a ``strict`` cookie would not be sent on
        # that cross-site navigation and the state check would always fail.
        samesite="lax",
        secure=_cookie_secure(),
        path="/",
    )


def _clear_oauth_state_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_OAUTH_STATE_COOKIE,
        path="/",
        samesite="lax",
        secure=_cookie_secure(),
    )


@router.get("/oauth/providers")
async def oauth_providers_status():
    """Report which OAuth providers are configured for this deployment."""
    from .. import oauth as oauth_module
    from ..models import OAuthProvidersStatus

    return OAuthProvidersStatus(
        google=oauth_module.is_configured("google"),
        github=oauth_module.is_configured("github"),
    ).model_dump()


@router.get("/oauth/{provider}/start")
@limiter.limit("10/minute")
async def oauth_start(request: Request, provider: str):
    """Redirect the user-agent to the IdP's consent screen.

    503 if the provider is recognised but not configured (env vars unset)
    so the SPA can surface a clearer message than the bare 404 from an
    unknown provider name.
    """
    import secrets as _secrets

    from fastapi.responses import RedirectResponse

    from .. import oauth as oauth_module

    try:
        prov = oauth_module.get_provider(provider)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    if not oauth_module.is_configured(provider):
        raise HTTPException(
            status_code=503,
            detail=f"OAuth provider {provider} not configured",
        )
    state = _secrets.token_urlsafe(32)
    redirect_uri = str(request.url_for("oauth_callback", provider=provider))
    authorize_url = prov.authorize_redirect(state, redirect_uri)
    resp = RedirectResponse(authorize_url, status_code=302)
    _set_oauth_state_cookie(resp, state)
    return resp


@router.get("/oauth/{provider}/callback", name="oauth_callback")
async def oauth_callback(
    provider: str, code: str, state: str, request: Request
):
    """Finish the OAuth dance: validate state, swap code, resolve user, log in."""
    from fastapi.responses import RedirectResponse

    from .. import oauth as oauth_module
    from ..auth_tokens import encode_session

    # ── 1. CSRF defence ────────────────────────────────────────────────────
    cookie_state = request.cookies.get(_OAUTH_STATE_COOKIE)
    if not cookie_state or not hmac.compare_digest(cookie_state, state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    # ── 2. Resolve provider config ─────────────────────────────────────────
    try:
        prov = oauth_module.get_provider(provider)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    if not oauth_module.is_configured(provider):
        raise HTTPException(
            status_code=503,
            detail=f"OAuth provider {provider} not configured",
        )

    # ── 3. Code → access token → userinfo ──────────────────────────────────
    redirect_uri = str(request.url_for("oauth_callback", provider=provider))
    try:
        token_data = await prov.exchange_code(code, redirect_uri)
    except Exception:
        logger.exception("OAuth code exchange failed for provider=%s", provider)
        raise HTTPException(status_code=502, detail="OAuth token exchange failed")
    access_token = token_data.get("access_token")
    if not access_token:
        # GitHub returns 200 with {"error": "..."} for some failure modes —
        # treat absence of the token as the canonical failure signal.
        raise HTTPException(status_code=400, detail="Failed to obtain access token")
    try:
        userinfo = await prov.fetch_userinfo(access_token)
    except Exception:
        logger.exception("OAuth userinfo fetch failed for provider=%s", provider)
        raise HTTPException(status_code=502, detail="OAuth userinfo fetch failed")

    try:
        norm = oauth_module.normalize_userinfo(provider, userinfo)
    except (KeyError, ValueError):
        logger.exception(
            "OAuth userinfo normalisation failed for provider=%s payload=%r",
            provider,
            userinfo,
        )
        raise HTTPException(status_code=502, detail="Malformed OAuth userinfo")

    # ── 4. Resolve to a local user ─────────────────────────────────────────
    # Order matters: OAuth-link lookup first so a user who linked then changed
    # their email at the IdP still resolves to their original account.
    user = db_auth.get_user_by_oauth(provider, norm["provider_user_id"])
    if user is None:
        existing = db_auth.get_user_by_email(norm["email"])
        if existing is not None:
            db_auth.link_oauth(
                existing["id"], provider, norm["provider_user_id"]
            )
            user = db_auth.get_user(existing["id"]) or existing
        else:
            try:
                _, user, _ = db_auth.signup_oauth(
                    provider=provider,
                    provider_user_id=norm["provider_user_id"],
                    email=norm["email"],
                    name=norm.get("name"),
                )
            except Exception:
                logger.exception(
                    "OAuth signup failed for provider=%s email=%s",
                    provider,
                    norm["email"],
                )
                raise HTTPException(status_code=500, detail="OAuth signup failed")

    if user.get("status") != "active":
        # Deactivated user trying to OAuth back in — same response as the
        # password path, no information leak.
        raise HTTPException(status_code=401, detail="invalid credentials")

    # ── 5. Issue session + bounce back to the SPA ──────────────────────────
    session_jwt = encode_session(user["id"], user["tenant_id"])
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=session_jwt,
        max_age=JWT_LIFETIME_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        path="/",
    )
    _clear_oauth_state_cookie(resp)
    return resp
