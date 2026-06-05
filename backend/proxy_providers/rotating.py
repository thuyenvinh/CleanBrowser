"""Residential rotating providers (gateway-style).

Pattern: ``host:port`` is a fixed gateway. The backend IP is selected by a
session id encoded into the username, e.g. BrightData::

    brd-customer-XXX-zone-residential-session-{ID}:password@brd.superproxy.io:22225

If ``sticky_session`` is set on the proxy row, use it verbatim → same backend
IP across reconnects. Otherwise a fresh session id is generated each call,
producing a new exit IP per ``resolve()``.

Each subclass implements ``_format_username`` according to its provider's
documented gateway authentication scheme. Country-code injection is deferred
to Phase 8 (sticky_session field carries the session id; country_code on the
proxy row is informational only at this layer).
"""

from __future__ import annotations

import uuid

from .base import ProxyInfo, ProxyProvider, ResolvedProxy


class RotatingProvider(ProxyProvider):
    """Base class for gateway-style residential providers."""

    name = "rotating"  # subclasses override

    def resolve(self, info: ProxyInfo) -> ResolvedProxy:
        session_id = info.sticky_session or uuid.uuid4().hex[:16]
        base_user = info.username or ""
        formatted = self._format_username(base_user, session_id)
        return ResolvedProxy(
            type=info.type,
            host=info.host,
            port=info.port,
            username=formatted or None,
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
    """BrightData residential / datacenter gateway.

    Expected configured username: ``brd-customer-{CID}-zone-{ZONE}``
    (no session suffix — provider appends one per ``resolve()``).
    Reference: https://brightdata.com/cp/api_examples
    """

    name = "brightdata"

    def _format_username(self, base_username: str, session_id: str) -> str:
        # BrightData expects the suffix even if the operator forgot to fill
        # the customer/zone prefix; gateway will reject the auth, but we keep
        # the format consistent for easier debugging.
        return f"{base_username}-session-{session_id}"


class Provider911(RotatingProvider):
    """911 S5 SOCKS5 rotating gateway.

    Configured username: customer login; provider appends session id.
    911 typically returns the same IP for the same session id for ~10 minutes.
    """

    name = "911"

    def _format_username(self, base_username: str, session_id: str) -> str:
        return f"{base_username}-session-{session_id}"


class SmartproxyProvider(RotatingProvider):
    """Smartproxy residential gateway.

    Configured username: provider-issued customer id.
    Adds ``-sessionduration-600`` so IPs stick for ~10 minutes.
    """

    name = "smartproxy"
    SESSION_DURATION_SECONDS = 600

    def _format_username(self, base_username: str, session_id: str) -> str:
        return (
            f"user-{base_username}"
            f"-session-{session_id}"
            f"-sessionduration-{self.SESSION_DURATION_SECONDS}"
        )


class IpRoyalProvider(RotatingProvider):
    """IPRoyal residential rotating proxy.

    Configured username: provider customer id. Lifetime in seconds is
    appended; 3600 keeps an IP for 1 hour which is the common ceiling.
    """

    name = "iproyal"
    SESSION_LIFETIME_SECONDS = 3600

    def _format_username(self, base_username: str, session_id: str) -> str:
        return (
            f"{base_username}"
            f"_session-{session_id}"
            f"_lifetime-{self.SESSION_LIFETIME_SECONDS}"
        )
