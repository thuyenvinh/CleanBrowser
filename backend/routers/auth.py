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
from ..dependencies import (
    SESSION_COOKIE,
    _is_https,
    get_current_user,
    require_verified_email,
)
from ..rate_limit import limiter
from ..models import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyPublic,
    EmailLoginRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MfaDisableRequest,
    MfaEnableRequest,
    MfaSetupResponse,
    ResendVerificationResponse,
    ResetPasswordRequest,
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
    # Anonymous bootstrap (signup / login) runs before tenant GUC is set
    # for the request; bypass RLS so the membership join returns rows.
    from ..middleware_rls import system_context

    with system_context():
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

    user = await get_optional_user(request)  # type: ignore[arg-type]
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
    from ..middleware_rls import system_context

    with system_context():
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

        # Anonymous lookup runs before any tenant GUC is set — bypass RLS
        # so the SELECT can find the user (same rationale as in signup /
        # the auth-status path).
        from ..middleware_rls import system_context

        with system_context():
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


# ---------------------------------------------------------------------------
# API keys — user-managed personal access tokens (Wave 2 closure)
#
# Backed by the ``user_api_keys`` table from migration 0003 and the
# ``create_api_key`` / ``get_api_key_by_token`` / ``revoke_api_key`` helpers
# in :mod:`backend.db_auth`. The dependency :func:`get_optional_user` also
# accepts these tokens via ``Authorization: Bearer <token>``, so a user can
# script the same operations they perform from the browser without sharing
# their password / JWT session cookie.
#
# Plaintext token is returned EXACTLY ONCE — on the POST response. We never
# persist the plaintext; only its SHA-256 lives in ``user_api_keys.key_hash``.
# ---------------------------------------------------------------------------


def _list_api_keys_for_user(user_id: str) -> list[dict[str, Any]]:
    """Return all API key rows owned by ``user_id`` (active + revoked).

    Inlined here (rather than added to :mod:`backend.db_auth`) so this wave
    doesn't churn the data layer module — see RULES in the task brief.
    """
    import psycopg2.extras

    from ..database import get_db
    from ..db_auth import _row_to_dict

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, name, scopes, last_used_at, created_at, revoked_at
                   FROM user_api_keys
                   WHERE user_id = %s
                   ORDER BY created_at DESC""",
                (user_id,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]  # type: ignore[misc]


def _api_key_public(row: dict[str, Any]) -> dict[str, Any]:
    """Project a ``user_api_keys`` row to the public-safe shape."""
    return ApiKeyPublic(
        id=row["id"],
        name=row["name"],
        scopes=list(row.get("scopes") or []),
        last_used_at=row.get("last_used_at"),
        created_at=row["created_at"],
        revoked_at=row.get("revoked_at"),
    ).model_dump()


@router.get("/api-keys")
async def list_api_keys(user: dict[str, Any] = Depends(get_current_user)):
    """Return the caller's API keys — never includes plaintext tokens."""
    rows = _list_api_keys_for_user(user["id"])
    return [_api_key_public(r) for r in rows]


@router.post("/api-keys", status_code=status.HTTP_201_CREATED, response_model=ApiKeyCreateResponse)
@limiter.limit("20/hour")
async def create_api_key_route(
    request: Request,
    body: ApiKeyCreateRequest,
    user: dict[str, Any] = Depends(require_verified_email),
):
    """Mint a new API key. Plaintext token is shown ONCE in the response."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    scopes = body.scopes if body.scopes is not None else ["*"]
    try:
        record, plaintext = db_auth.create_api_key(
            user["id"], name=name, scopes=scopes
        )
    except Exception:
        logger.exception("create_api_key failed for user=%s", user["id"])
        raise HTTPException(status_code=500, detail="failed to create api key")
    return ApiKeyCreateResponse(
        key=ApiKeyPublic(
            id=record["id"],
            name=record["name"],
            scopes=list(record.get("scopes") or []),
            last_used_at=record.get("last_used_at"),
            created_at=record["created_at"],
            revoked_at=record.get("revoked_at"),
        ),
        token=plaintext,
        warning=(
            "This token will only be shown once. Save it securely — "
            "you will not be able to retrieve it again."
        ),
    )


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key_route(
    key_id: str,
    user: dict[str, Any] = Depends(get_current_user),
):
    """Revoke an API key the caller owns.

    Returns 404 (not 403) when the key belongs to someone else so we don't
    leak the existence of keys across users.
    """
    rows = _list_api_keys_for_user(user["id"])
    if not any(r["id"] == key_id for r in rows):
        raise HTTPException(status_code=404, detail="api key not found")
    db_auth.revoke_api_key(key_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api-keys/{key_id}/rotate", status_code=status.HTTP_201_CREATED)
@limiter.limit("20/hour")
async def rotate_api_key_route(
    request: Request,
    key_id: str,
    user: dict[str, Any] = Depends(require_verified_email),
):
    """Rotate an API key: mint a fresh secret with the SAME name + scopes,
    then revoke the original — atomic from the caller's POV.

    Useful when a token may have leaked: a new key + new plaintext is issued
    in the response (shown ONCE, same as create), and the original is marked
    revoked so existing clients fail fast and force the operator to update
    their stored secret. We deliberately reuse the existing
    ``db_auth.create_api_key`` / ``db_auth.revoke_api_key`` primitives rather
    than introducing a new ``rotate`` DB helper — keeps the data layer
    untouched per the M11 brief.
    """
    keys = _list_api_keys_for_user(user["id"])
    existing = next(
        (k for k in keys if k["id"] == key_id and not k.get("revoked_at")),
        None,
    )
    if not existing:
        raise HTTPException(
            status_code=404, detail="Key not found or already revoked"
        )

    try:
        record, plaintext = db_auth.create_api_key(
            user["id"],
            name=existing["name"],
            scopes=list(existing.get("scopes") or []),
        )
    except Exception:
        logger.exception("rotate_api_key failed for user=%s", user["id"])
        raise HTTPException(status_code=500, detail="failed to rotate api key")
    db_auth.revoke_api_key(key_id)

    return ApiKeyCreateResponse(
        key=ApiKeyPublic(
            id=record["id"],
            name=record["name"],
            scopes=list(record.get("scopes") or []),
            last_used_at=record.get("last_used_at"),
            created_at=record["created_at"],
            revoked_at=record.get("revoked_at"),
        ),
        token=plaintext,
        warning=(
            "Save the new token now — old key has been revoked."
        ),
    )


# ---------------------------------------------------------------------------
# Password reset (bug C6 closure)
#
# Flow (mirrors email verification above):
#   1. Unauthenticated POST /forgot-password {email}. We respond 200 with a
#      generic message regardless of whether the email exists — this is a
#      hard requirement, otherwise the endpoint becomes a username-
#      enumeration oracle.
#   2. If the email DOES exist, we mint a 1h SHA-256-stored token (see
#      :func:`backend.db_auth.create_password_reset_token`) and email the
#      plaintext as a link pointing at the SPA's ``/reset-password?token=…``
#      route. The SPA collects the new password and POSTs to
#      /reset-password.
#   3. /reset-password consumes the token (one-shot) and updates the
#      ``users.password_hash``. Sessions issued before the reset stay valid
#      because they live as opaque JWTs — that's an acceptable trade-off
#      for now; a follow-up wave can wire a per-user version counter into
#      :mod:`backend.auth_tokens` to invalidate old cookies on reset.
#
# Rate-limits are deliberately tight: forgot is bound at 5/h to slow down
# email-bombing a single victim; reset is 10/h because a legitimate user
# might fat-finger the new password and retry a couple of times.
# ---------------------------------------------------------------------------


@router.post("/forgot-password")
@limiter.limit("5/hour")
async def forgot_password(request: Request, body: ForgotPasswordRequest):
    """Kick off the reset flow for ``body.email``.

    Always returns 200 with the same neutral message — whether or not the
    email maps to a known user — so attackers cannot use this endpoint to
    discover which addresses have CleanBrowser accounts. The send itself
    is wrapped in a ``try`` so a flaky SMTP server can't turn the silent-
    success contract into a 500.
    """
    from ..middleware_rls import system_context

    with system_context():
        user = db_auth.get_user_by_email(body.email)
        if user:
            try:
                _, token = db_auth.create_password_reset_token(user["id"])
                # ``request.base_url`` already ends with ``/`` so we don't add
                # another. Lands on the SPA, which mounts the ResetPasswordPage
                # on ``/reset-password`` and pulls ``?token=`` off the query.
                reset_url = f"{request.base_url}reset-password?token={token}"
                email_sender.send_password_reset_email(user["email"], reset_url)
            except Exception:
                logger.exception(
                    "forgot-password send failed for user=%s", user.get("id")
                )
    return {
        "message": (
            "If that email exists, a reset link has been sent. "
            "Check your inbox (and spam)."
        )
    }


@router.post("/reset-password")
@limiter.limit("10/hour")
async def reset_password(request: Request, body: ResetPasswordRequest):
    """Consume a reset token and set the user's new password.

    The Pydantic model already enforces ``min_length=8`` on
    ``new_password`` but we re-check explicitly so a future schema relax
    can't silently weaken the floor. Token consumption is one-shot — a
    second POST with the same token gets the generic 400.
    """
    # Anonymous endpoint — bypass RLS for the token lookup + password update.
    from ..middleware_rls import system_context

    with system_context():
        user_id = db_auth.consume_password_reset_token(body.token)
        if not user_id:
            raise HTTPException(
                status_code=400, detail="Invalid or expired reset link"
            )
        if len(body.new_password) < 8:
            raise HTTPException(
                status_code=400, detail="Password must be at least 8 characters"
            )
        db_auth.update_user_password_by_id(user_id, body.new_password)
    return {"reset": True}
