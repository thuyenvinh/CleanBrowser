"""GeoIP lookup. Phase 2 uses online API; Phase 3 will swap to Maxmind GeoLite2 mmdb.

Standalone module exposing ``lookup_country(ip)`` (async) and ``lookup_timezone(cc)``.
The country lookup hits a free API (ipapi.co by default) with bounded in-memory cache.
All errors are swallowed and return ``None``; this is the contract the health-check
worker relies on.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Bounded cache: ip -> country_code (or None for negative cache).
_CACHE: dict[str, Optional[str]] = {}
_CACHE_MAX = 1000

IPAPI_URL = os.environ.get("GEOIP_API_URL", "https://ipapi.co/{ip}/json/")
IPAPI_TIMEOUT = 5


async def lookup_country(ip: str) -> Optional[str]:
    """Return ISO country code (uppercase) for *ip*, or ``None``.

    Never raises. Results are cached (including negatives) up to ``_CACHE_MAX``
    entries; on overflow the cache is wiped (cheap & simple — no real LRU).
    """
    if not ip or not isinstance(ip, str):
        return None
    if ip in _CACHE:
        return _CACHE[ip]

    try:
        # Lazy import so the module is importable in environments without httpx
        import httpx  # type: ignore
    except ImportError:
        logger.warning("httpx not installed; geoip disabled")
        return None

    url = IPAPI_URL.format(ip=ip)
    result: Optional[str] = None
    try:
        async with httpx.AsyncClient(timeout=IPAPI_TIMEOUT) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            code = data.get("country_code") or data.get("country")
            if isinstance(code, str) and 2 <= len(code) <= 3:
                result = code.upper()
    except Exception as e:  # noqa: BLE001 — contract: never raise
        logger.warning("geoip lookup failed for %s: %s", ip, type(e).__name__)
        result = None

    # Bounded cache (evict-all on overflow — keep it simple)
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[ip] = result
    return result


def lookup_country_sync(ip: str) -> Optional[str]:
    """Sync wrapper for ``lookup_country``. For CLI / one-off use only."""
    return asyncio.run(lookup_country(ip))


# ---------------------------------------------------------------------------
# Country -> primary timezone mapping (static).
# Covers ~40 of the most common countries used by residential proxy pools.
# ---------------------------------------------------------------------------
_COUNTRY_TO_TIMEZONE: dict[str, str] = {
    "US": "America/New_York",
    "CA": "America/Toronto",
    "MX": "America/Mexico_City",
    "BR": "America/Sao_Paulo",
    "AR": "America/Argentina/Buenos_Aires",
    "CL": "America/Santiago",
    "CO": "America/Bogota",
    "GB": "Europe/London",
    "IE": "Europe/Dublin",
    "FR": "Europe/Paris",
    "DE": "Europe/Berlin",
    "IT": "Europe/Rome",
    "ES": "Europe/Madrid",
    "PT": "Europe/Lisbon",
    "NL": "Europe/Amsterdam",
    "BE": "Europe/Brussels",
    "CH": "Europe/Zurich",
    "AT": "Europe/Vienna",
    "SE": "Europe/Stockholm",
    "NO": "Europe/Oslo",
    "DK": "Europe/Copenhagen",
    "FI": "Europe/Helsinki",
    "PL": "Europe/Warsaw",
    "CZ": "Europe/Prague",
    "RO": "Europe/Bucharest",
    "GR": "Europe/Athens",
    "TR": "Europe/Istanbul",
    "RU": "Europe/Moscow",
    "UA": "Europe/Kiev",
    "VN": "Asia/Ho_Chi_Minh",
    "TH": "Asia/Bangkok",
    "SG": "Asia/Singapore",
    "MY": "Asia/Kuala_Lumpur",
    "ID": "Asia/Jakarta",
    "PH": "Asia/Manila",
    "JP": "Asia/Tokyo",
    "KR": "Asia/Seoul",
    "CN": "Asia/Shanghai",
    "HK": "Asia/Hong_Kong",
    "TW": "Asia/Taipei",
    "IN": "Asia/Kolkata",
    "PK": "Asia/Karachi",
    "AE": "Asia/Dubai",
    "SA": "Asia/Riyadh",
    "IL": "Asia/Jerusalem",
    "AU": "Australia/Sydney",
    "NZ": "Pacific/Auckland",
    "ZA": "Africa/Johannesburg",
    "EG": "Africa/Cairo",
    "NG": "Africa/Lagos",
}


def lookup_timezone(country_code: Optional[str]) -> Optional[str]:
    """Return a representative IANA timezone for *country_code*, or ``None``."""
    if not country_code or not isinstance(country_code, str):
        return None
    return _COUNTRY_TO_TIMEZONE.get(country_code.upper())
