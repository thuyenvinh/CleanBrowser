"""Provider registry — single source of truth for ``provider`` field values."""

from __future__ import annotations

from .base import ProxyProvider
from .manual import ManualProvider
from .rotating import (
    BrightDataProvider,
    IpRoyalProvider,
    Provider911,
    SmartproxyProvider,
)

_REGISTRY: dict[str, ProxyProvider] = {
    "manual": ManualProvider(),
    "brightdata": BrightDataProvider(),
    "911": Provider911(),
    "smartproxy": SmartproxyProvider(),
    "iproyal": IpRoyalProvider(),
}


def get_provider(name: str) -> ProxyProvider:
    """Look up a provider by name. Raises ``ValueError`` if unknown."""
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown proxy provider: {name}") from None


def list_providers() -> list[str]:
    """Return registered provider names in insertion order."""
    return list(_REGISTRY.keys())
