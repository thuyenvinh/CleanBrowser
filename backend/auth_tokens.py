"""JWT session token helpers (HS256).

A tiny wrapper around PyJWT used by the auth router and dependencies. The
secret comes from the ``JWT_SECRET`` env var; if unset we emit a *loud* warning
and fall back to a per-process random secret so dev / tests still work but
restarting the server invalidates every outstanding session (which is the
correct behaviour — never silently sign with a static fallback in prod).

The token payload is intentionally minimal::

    {"sub": <user_id>, "tid": <tenant_id>, "iat": <epoch>, "exp": <epoch>}

Role and email are *not* embedded — the API layer looks the user up on every
request so changes (password reset, deactivation, role bump) take effect
immediately instead of waiting for the JWT to expire.
"""

from __future__ import annotations

import datetime
import logging
import os
import secrets
from typing import Any

import jwt

logger = logging.getLogger("cloakbrowser.auth")

JWT_ALGO = "HS256"
JWT_LIFETIME_SECONDS = 86_400  # 24h


def _load_secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if secret:
        return secret
    # No secret set: generate a random one for this process. Loud warning so it
    # doesn't silently happen in production. Tokens won't survive a restart.
    fallback = secrets.token_urlsafe(48)
    logger.warning(
        "JWT_SECRET is not set — generated an ephemeral per-process secret. "
        "Sessions will be invalidated on restart. Set JWT_SECRET in production."
    )
    return fallback


JWT_SECRET: str = _load_secret()


def encode_session(user_id: str, tenant_id: str) -> str:
    """Return a signed JWT for ``user_id`` (tenant_id is included as ``tid``)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    payload = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "iat": int(now.timestamp()),
        "exp": int((now + datetime.timedelta(seconds=JWT_LIFETIME_SECONDS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def decode_session(token: str) -> dict[str, Any] | None:
    """Decode a JWT. Returns ``None`` on any failure (expired, bad sig, etc.).

    Failures are logged at DEBUG with only the exception type so a SIEM can
    distinguish "expired" from "tampered" without dumping the bearer secret.
    """
    if not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.PyJWTError as exc:
        logger.debug("JWT decode failed: %s", type(exc).__name__)
        return None
