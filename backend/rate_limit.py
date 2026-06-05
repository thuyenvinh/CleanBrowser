"""Per-IP rate limiting via slowapi (wraps limits lib).

Configure via env:
  RATE_LIMIT_STORAGE_URI — default 'memory://'. For multi-instance use
                           'redis://host:6379' for shared counters.
  RATE_LIMIT_ENABLED      — set 'false' to disable entirely (testing).
"""
from __future__ import annotations
import os
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

def _enabled() -> bool:
    return os.environ.get("RATE_LIMIT_ENABLED", "true").lower() != "false"

def _key_func(request):
    # Prefer X-Forwarded-For (set by reverse proxy), fall back to remote addr.
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)

storage_uri = os.environ.get("RATE_LIMIT_STORAGE_URI", "memory://")
limiter = Limiter(
    key_func=_key_func,
    storage_uri=storage_uri,
    enabled=_enabled(),
    default_limits=[],  # opt-in per route
    strategy="fixed-window",
)

__all__ = ["limiter", "RateLimitExceeded", "_rate_limit_exceeded_handler"]
