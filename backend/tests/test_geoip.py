"""Smoke tests for backend.geoip — no real HTTP."""
from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend import geoip


@pytest.fixture(autouse=True)
def _clear_cache():
    geoip._CACHE.clear()
    yield
    geoip._CACHE.clear()


@pytest.mark.asyncio
async def test_empty_ip_returns_none():
    assert await geoip.lookup_country("") is None
    assert await geoip.lookup_country(None) is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_cache_hit_skips_http():
    geoip._CACHE["1.2.3.4"] = "US"
    # If http were called, missing httpx mock would still return None — but cache short-circuits.
    with patch.dict(sys.modules, {"httpx": None}):
        assert await geoip.lookup_country("1.2.3.4") == "US"


@pytest.mark.asyncio
async def test_httpx_missing_returns_none():
    # Force ImportError by injecting a sentinel that raises on attr access? Easier:
    # remove cache, monkeypatch importer.
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "httpx":
            raise ImportError("no httpx")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        assert await geoip.lookup_country("8.8.8.8") is None


@pytest.mark.asyncio
async def test_parse_country_code_from_response():
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json = MagicMock(return_value={"country_code": "vn"})

    fake_client = MagicMock()
    fake_client.get = AsyncMock(return_value=fake_resp)
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.AsyncClient = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {"httpx": fake_httpx}):
        assert await geoip.lookup_country("9.9.9.9") == "VN"
    # cached
    assert geoip._CACHE["9.9.9.9"] == "VN"


@pytest.mark.asyncio
async def test_http_error_returns_none_and_caches():
    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=RuntimeError("boom"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.AsyncClient = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]

    with patch.dict(sys.modules, {"httpx": fake_httpx}):
        assert await geoip.lookup_country("7.7.7.7") is None
    assert geoip._CACHE["7.7.7.7"] is None


def test_lookup_timezone_known():
    assert geoip.lookup_timezone("VN") == "Asia/Ho_Chi_Minh"
    assert geoip.lookup_timezone("us") == "America/New_York"
    assert geoip.lookup_timezone("JP") == "Asia/Tokyo"


def test_lookup_timezone_unknown_or_empty():
    assert geoip.lookup_timezone(None) is None
    assert geoip.lookup_timezone("") is None
    assert geoip.lookup_timezone("ZZ") is None
