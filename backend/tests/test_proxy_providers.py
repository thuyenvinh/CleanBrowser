"""Smoke tests for the proxy provider adapter framework."""

from __future__ import annotations

import pytest

from backend.proxy_providers import (
    ProxyInfo,
    ResolvedProxy,
    get_provider,
    list_providers,
)


def _info(**overrides) -> ProxyInfo:
    base = dict(
        id="p1",
        type="http",
        host="gw.example.com",
        port=8080,
        username="user",
        password="pass",
        rotation_url=None,
        sticky_session=None,
        country_code="US",
    )
    base.update(overrides)
    return ProxyInfo(**base)


def test_manual_provider_resolve_passthrough():
    resolved = get_provider("manual").resolve(_info())
    assert (resolved.host, resolved.port, resolved.username, resolved.password) == (
        "gw.example.com", 8080, "user", "pass",
    )
    assert resolved.country_code == "US"


def test_rotating_sticky_session_honored():
    resolved = get_provider("brightdata").resolve(
        _info(rotation_url="https://api.brightdata.example/rotate", sticky_session="abc123")
    )
    assert resolved.username == "user-session-abc123"
    # Sticky → deterministic across calls.
    again = get_provider("brightdata").resolve(
        _info(rotation_url="https://api.brightdata.example/rotate", sticky_session="abc123")
    )
    assert again.username == resolved.username


def test_rotating_autogenerates_session_when_sticky_none():
    info = _info(rotation_url="https://api.brightdata.example/rotate", sticky_session=None)
    a = get_provider("911").resolve(info)
    b = get_provider("911").resolve(info)
    assert a.username and a.username.startswith("user-session-")
    assert b.username and b.username.startswith("user-session-")
    assert a.username != b.username  # fresh session per resolve()


def test_registry_lookup_and_listing():
    assert set(list_providers()) >= {"manual", "brightdata", "911", "smartproxy", "iproyal"}
    with pytest.raises(ValueError):
        get_provider("does-not-exist")


def test_resolved_proxy_to_url_encodes_special_chars():
    rp = ResolvedProxy(
        type="http", host="h.example", port=1080,
        username="u@ser", password="p a:ss/?",
    )
    assert rp.to_url() == "http://u%40ser:p%20a%3Ass%2F%3F@h.example:1080"
    socks = ResolvedProxy(type="socks5", host="h", port=1, username=None, password=None)
    assert socks.to_url() == "socks5://h:1"


# ---------------------------------------------------------------------------
# Per-provider username format tests (Phase 2 follow-up).
# ---------------------------------------------------------------------------


def _rinfo(username="myuser", sticky=None):
    """Builder used by the per-provider format tests below."""
    return ProxyInfo(
        id="x",
        type="http",
        host="proxy.example.com",
        port=22225,
        username=username,
        password="pw",
        rotation_url=None,
        sticky_session=sticky,
        country_code=None,
    )


def test_brightdata_format():
    r = get_provider("brightdata").resolve(
        _rinfo(username="brd-customer-C123-zone-residential", sticky="abc")
    )
    assert r.username == "brd-customer-C123-zone-residential-session-abc"


def test_911_format():
    r = get_provider("911").resolve(_rinfo(username="login911", sticky="xyz"))
    assert r.username == "login911-session-xyz"


def test_smartproxy_format_includes_duration():
    r = get_provider("smartproxy").resolve(_rinfo(username="spuser", sticky="sess1"))
    assert r.username == "user-spuser-session-sess1-sessionduration-600"


def test_iproyal_format_includes_lifetime():
    r = get_provider("iproyal").resolve(_rinfo(username="ip_user", sticky="s2"))
    assert r.username == "ip_user_session-s2_lifetime-3600"


def test_brightdata_handles_missing_base_username():
    r = get_provider("brightdata").resolve(_rinfo(username=None, sticky="only"))
    assert r.username == "-session-only"  # gracefully degrades


def test_rotating_resolve_to_url_includes_session():
    r = get_provider("smartproxy").resolve(_rinfo(username="u", sticky="sX"))
    url = r.to_url()
    assert "session-sX" in url
    assert "sessionduration-600" in url
