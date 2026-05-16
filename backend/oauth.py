"""OAuth 2.0 Authorization Code helpers for Google and GitHub.

Phase 1 (task WW) — provider-side abstraction for the OAuth login flow
defined in ``docs/ARCHITECTURE`` §2.3. The router layer
(:mod:`backend.routers.auth`) drives the flow; this module is purely a
config + HTTP wrapper so adding a third IdP is a one-function change.

Design notes:

* **No PKCE** in Phase 1 — both Google and GitHub support classic
  Authorization Code with a server-side client secret, which is the
  natural fit for a confidential server-rendered callback. PKCE will be
  added when the same flow is exposed to a public client (SPA / mobile).
* **No persistent provider object.** Configuration is read fresh from
  the environment on every call to :func:`get_provider`, so a deployment
  can rotate ``*_OAUTH_CLIENT_SECRET`` without restarting the worker.
  The cost is one ``os.environ`` lookup per OAuth round-trip, which is
  noise next to the network calls the flow makes anyway.
* **``httpx`` imported lazily** inside :meth:`OAuthProvider.exchange_code`
  / :meth:`OAuthProvider.fetch_userinfo` so importing this module at
  app startup (which the router does) doesn't pay the cost of an HTTP
  client wired up to a connection pool that may never be used (e.g. when
  no OAuth provider is configured).
* **Normalisation** of provider userinfo into a flat
  ``{provider_user_id, email, name}`` dict lives here rather than in the
  router so the router stays declarative: lookup → link-or-create →
  issue session.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode


@dataclass
class OAuthProvider:
    """One OAuth 2.0 Authorization Code provider."""

    name: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str
    client_id: str
    client_secret: str

    def authorize_redirect(self, state: str, redirect_uri: str) -> str:
        """Build the URL to redirect the user-agent to for consent."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": self.scope,
            "state": state,
            # ``online`` access token only — we don't need a refresh token
            # because we re-prompt the user to log in if their session
            # cookie expires. Avoids storing/managing refresh tokens.
            "access_type": "online",
        }
        return f"{self.authorize_url}?{urlencode(params)}"

    async def exchange_code(
        self, code: str, redirect_uri: str
    ) -> dict[str, Any]:
        """Exchange the one-shot ``code`` for an access token.

        Both Google and GitHub accept the standard form-encoded payload
        with ``Accept: application/json`` to coerce GitHub into a JSON
        response (its default is form-encoded — a foot-gun).
        """
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                self.token_url,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()

    async def fetch_userinfo(self, access_token: str) -> dict[str, Any]:
        """Fetch the IdP-specific user profile, authenticated by Bearer token."""
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                self.userinfo_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                    # GitHub returns a slimmer payload for unidentified
                    # clients; set a UA so we always get the v3 user shape.
                    "User-Agent": "CleanBrowser-OAuth",
                },
            )
            resp.raise_for_status()
            return resp.json()


# ---------------------------------------------------------------------------
# Factory: one provider per name. Reads env on each call so secrets can be
# rotated without bouncing the process.
# ---------------------------------------------------------------------------


def _get_google() -> OAuthProvider:
    return OAuthProvider(
        name="google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://www.googleapis.com/oauth2/v3/userinfo",
        # ``openid`` makes Google include the ``sub`` claim in userinfo;
        # ``email profile`` give us the human-facing fields.
        scope="openid email profile",
        client_id=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
        client_secret=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
    )


def _get_github() -> OAuthProvider:
    return OAuthProvider(
        name="github",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        userinfo_url="https://api.github.com/user",
        # ``user:email`` is enough to read the user's primary email even
        # when it is set to ``private`` on their profile (Phase 1 fallback
        # uses noreply.github.com if email comes back NULL).
        scope="read:user user:email",
        client_id=os.environ.get("GITHUB_OAUTH_CLIENT_ID", ""),
        client_secret=os.environ.get("GITHUB_OAUTH_CLIENT_SECRET", ""),
    )


_FACTORIES = {
    "google": _get_google,
    "github": _get_github,
}


def get_provider(name: str) -> OAuthProvider:
    """Return the provider config for ``name`` or raise ``ValueError``."""
    factory = _FACTORIES.get(name)
    if factory is None:
        raise ValueError(f"Unknown OAuth provider: {name}")
    return factory()


def is_configured(provider_name: str) -> bool:
    """Whether ``provider_name`` has both ``client_id`` and ``client_secret`` set."""
    try:
        p = get_provider(provider_name)
    except ValueError:
        return False
    return bool(p.client_id and p.client_secret)


# ---------------------------------------------------------------------------
# Userinfo normalisation
# ---------------------------------------------------------------------------


def normalize_userinfo(provider: str, info: dict[str, Any]) -> dict[str, Any]:
    """Project an IdP userinfo payload to ``{provider_user_id, email, name}``.

    * Google: ``sub`` is the stable subject id, ``email`` is verified by
      Google when ``email_verified`` is True (we still trust it for v1).
    * GitHub: ``id`` is numeric — stringified to keep the column ``TEXT``.
      If the user's email is private and not returned, fall back to the
      noreply mailbox GitHub mints for every account. That's still a
      stable per-user identifier, just not deliverable mail; the OAuth
      identity itself remains keyed on the numeric id.
    """
    if provider == "google":
        return {
            "provider_user_id": info["sub"],
            "email": info["email"],
            "name": info.get("name"),
        }
    if provider == "github":
        email = info.get("email") or f"{info['login']}@users.noreply.github.com"
        return {
            "provider_user_id": str(info["id"]),
            "email": email,
            "name": info.get("name") or info.get("login"),
        }
    raise ValueError(f"Unknown OAuth provider: {provider}")
