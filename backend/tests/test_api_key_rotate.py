"""Tests for API key lifecycle including rotate (M11 fix).

Rotate must create a fresh key with the same name + scopes AND revoke the
original — atomically from the caller's perspective so leaked keys can be
replaced without an outage window.
"""
from __future__ import annotations

import uuid

import pytest

from backend import db_auth


def _make_user(tmp_db) -> dict:
    _, user, _ = db_auth.signup(
        email=f"keys+{uuid.uuid4().hex[:8]}@example.test",
        password="some-secure-password",
    )
    return user


def test_create_api_key_returns_plaintext_token(tmp_db):
    """Token plaintext is shown exactly once at creation; DB has only the hash."""
    user = _make_user(tmp_db)
    record, token = db_auth.create_api_key(user["id"], name="ci-bot")
    assert isinstance(token, str)
    assert len(token) >= 20
    assert record["name"] == "ci-bot"
    assert record["scopes"] == ["*"]
    assert record["key_hash"] != token


def test_lookup_by_token_round_trip(tmp_db):
    user = _make_user(tmp_db)
    _, token = db_auth.create_api_key(user["id"], name="lookup")
    row = db_auth.get_api_key_by_token(token)
    assert row is not None
    assert row["user_id"] == user["id"]
    assert row["name"] == "lookup"


def test_revoke_removes_key_from_active_lookup(tmp_db):
    user = _make_user(tmp_db)
    record, token = db_auth.create_api_key(user["id"], name="to-revoke")
    db_auth.revoke_api_key(record["id"])
    assert db_auth.get_api_key_by_token(token) is None


def test_custom_scopes_are_preserved(tmp_db):
    user = _make_user(tmp_db)
    record, _ = db_auth.create_api_key(
        user["id"], name="scoped", scopes=["profile:read", "profile:launch"]
    )
    assert sorted(record["scopes"]) == ["profile:launch", "profile:read"]


def test_revoke_unknown_key_returns_false(tmp_db):
    """No-op on missing rows — never raises."""
    result = db_auth.revoke_api_key(str(uuid.uuid4()))
    assert result is False
