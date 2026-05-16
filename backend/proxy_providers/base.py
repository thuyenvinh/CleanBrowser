"""Abstract proxy provider interface.

Phase 2 scaffold: providers are pure Python logic — they translate a stored
``ProxyInfo`` (DB row) into a ``ResolvedProxy`` (concrete host:port:user:pass)
that the browser launcher can consume.

No HTTP. Rotation APIs (911, BrightData, ...) will be wired in a later wave
once the HTTP client + background worker land.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote


@dataclass
class ProxyInfo:
    """Read-only view of a proxy row passed to providers.

    ``password`` is expected to be decrypted plaintext at this layer — providers
    must never persist it.
    """

    id: str
    type: str
    host: str
    port: int
    username: Optional[str]
    password: Optional[str]
    rotation_url: Optional[str]
    sticky_session: Optional[str]
    country_code: Optional[str]


@dataclass
class ResolvedProxy:
    """Concrete proxy coordinates returned by a provider for a launch."""

    type: str
    host: str
    port: int
    username: Optional[str]
    password: Optional[str]
    country_code: Optional[str] = None

    def to_url(self) -> str:
        """Render as ``scheme://[user:pass@]host:port``.

        Special characters in credentials are percent-encoded.
        """
        scheme = (self.type or "http").lower()
        auth = ""
        if self.username:
            user = quote(self.username, safe="")
            if self.password is not None:
                pwd = quote(self.password, safe="")
                auth = f"{user}:{pwd}@"
            else:
                auth = f"{user}@"
        return f"{scheme}://{auth}{self.host}:{self.port}"


class ProxyProvider(ABC):
    """Adapter for a proxy source (manual entry, residential gateway, ...)."""

    name: str = "base"

    @abstractmethod
    def resolve(self, info: ProxyInfo) -> ResolvedProxy:
        """Return concrete launch coordinates.

        Rotating providers may return different credentials on each call when
        ``sticky_session`` is unset.
        """

    def healthcheck_target(self, info: ProxyInfo) -> ResolvedProxy:
        """Return the proxy to probe during health-check. Defaults to ``resolve``."""
        return self.resolve(info)
