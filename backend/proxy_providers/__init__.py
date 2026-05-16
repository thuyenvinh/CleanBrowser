"""Proxy provider adapter framework (Phase 2 scaffold)."""

from .base import ProxyInfo, ProxyProvider, ResolvedProxy
from .registry import get_provider, list_providers

__all__ = [
    "ProxyProvider",
    "ProxyInfo",
    "ResolvedProxy",
    "get_provider",
    "list_providers",
]
