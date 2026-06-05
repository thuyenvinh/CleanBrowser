"""Manual proxy provider — user pasted host/port/user/pass by hand."""

from __future__ import annotations

from .base import ProxyInfo, ProxyProvider, ResolvedProxy


class ManualProvider(ProxyProvider):
    """Pass-through provider: returns exactly what the user entered."""

    name = "manual"

    def resolve(self, info: ProxyInfo) -> ResolvedProxy:
        return ResolvedProxy(
            type=info.type,
            host=info.host,
            port=info.port,
            username=info.username,
            password=info.password,
            country_code=info.country_code,
        )

    def healthcheck_target(self, info: ProxyInfo) -> ResolvedProxy:
        return self.resolve(info)
