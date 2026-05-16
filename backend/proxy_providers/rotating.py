"""Residential rotating providers (gateway-style).

Pattern: ``host:port`` is a fixed gateway. The backend IP is selected by a
session id encoded into the username, e.g. BrightData::

    brd-customer-XXX-zone-residential-session-{ID}:password@brd.superproxy.io:22225

If ``sticky_session`` is set on the proxy row, use it verbatim → same backend
IP across reconnects. Otherwise a fresh session id is generated each call,
producing a new exit IP per ``resolve()``.

NOTE: scaffold only — no HTTP calls. Real per-provider username/session
formats will be tuned in a later wave; subclasses can override
``_format_username``.
"""

from __future__ import annotations

import uuid

from .base import ProxyInfo, ProxyProvider, ResolvedProxy


class RotatingProvider(ProxyProvider):
    """Base class for gateway-style residential providers."""

    name = "rotating"  # subclasses override

    def resolve(self, info: ProxyInfo) -> ResolvedProxy:
        session_id = info.sticky_session
        if session_id is None and info.rotation_url:
            # Rotating mode without sticky: mint a fresh session id per call.
            session_id = uuid.uuid4().hex
        base_user = info.username or ""
        username = (
            self._format_username(base_user, session_id)
            if session_id is not None
            else (info.username if info.username else None)
        )
        return ResolvedProxy(
            type=info.type,
            host=info.host,
            port=info.port,
            username=username,
            password=info.password,
            country_code=info.country_code,
        )

    def healthcheck_target(self, info: ProxyInfo) -> ResolvedProxy:
        return self.resolve(info)

    def _format_username(self, base_username: str, session_id: str) -> str:
        """Inject session id into username. Default pattern: ``base-session-<id>``."""
        if not base_username:
            return f"session-{session_id}"
        return f"{base_username}-session-{session_id}"


class BrightDataProvider(RotatingProvider):
    name = "brightdata"
    # TODO: customize _format_username for BrightData's exact zone/session pattern.


class Provider911(RotatingProvider):
    name = "911"


class SmartproxyProvider(RotatingProvider):
    name = "smartproxy"


class IpRoyalProvider(RotatingProvider):
    name = "iproyal"
