"""Tests for forgot-password / reset-password flow (C6 fix).

Tokens are one-shot, expire in 1 hour, and store only the SHA-256 hash so
even an exposed DB doesn't grant password resets.
"""
from __future__ import annotations

import datetime
import uuid

import pytest

from backend import db_auth


def _make_user(tmp_db) -> dict:
    _, user, _ = db_auth.signup(
        email=f"reset+{uuid.uuid4().hex[:8]}@example.test",
        password="initial-password-123",
    )
    return user


def test_create_password_reset_token_returns_plaintext(tmp_db):
    """Token returned exactly once; DB stores only the hash."""
    user = _make_user(tmp_db)
    record, token = db_auth.create_password_reset_token(user["id"])
    assert isinstance(token, str)
    assert len(token) >= 30
    assert record["token_hash"] != token  # hash, not plaintext


def test_consume_token_returns_user_id_first_time(tmp_db):
    user = _make_user(tmp_db)
    _, token = db_auth.create_password_reset_token(user["id"])
    consumed = db_auth.consume_password_reset_token(token)
    assert consumed == user["id"]


def test_consume_token_second_time_returns_none(tmp_db):
    """One-shot — the second consume should be rejected even with the same token."""
    user = _make_user(tmp_db)
    _, token = db_auth.create_password_reset_token(user["id"])
    db_auth.consume_password_reset_token(token)
    assert db_auth.consume_password_reset_token(token) is None


def test_consume_invalid_token_returns_none(tmp_db):
    """Random/garbage tokens never resolve."""
    assert db_auth.consume_password_reset_token("not-a-real-token") is None


def test_password_reset_updates_password(tmp_db):
    """update_user_password_by_id changes the hash so old creds stop working."""
    user = _make_user(tmp_db)
    ok = db_auth.update_user_password_by_id(user["id"], "brand-new-password-456")
    assert ok is True
    refreshed = db_auth.get_user(user["id"])
    assert refreshed["password_hash"] != user["password_hash"]
    assert db_auth.verify_password("brand-new-password-456", refreshed["password_hash"])
    assert not db_auth.verify_password("initial-password-123", refreshed["password_hash"])
