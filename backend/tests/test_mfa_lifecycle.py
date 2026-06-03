"""Tests for the MFA (TOTP) lifecycle helpers in :mod:`backend.db_auth`.

Coverage: enable_mfa / disable_mfa / is_mfa_enabled / verify_totp. The
helpers are thin wrappers around a single ``mfa_secret`` column, but the
combination "enable then verify against pyotp.now()" is the critical
contract — if these break, every authenticator app silently stops working.
"""
from __future__ import annotations

import uuid

import pyotp
import pytest

from backend import db_auth


def _make_user(tmp_db) -> dict:
    _, user, _ = db_auth.signup(
        email=f"mfa+{uuid.uuid4().hex[:8]}@example.test",
        password="password123",
    )
    return user


def test_enable_mfa_persists_secret(tmp_db):
    """After enable_mfa, is_mfa_enabled returns True."""
    user = _make_user(tmp_db)
    assert db_auth.is_mfa_enabled(user["id"]) is False
    secret = pyotp.random_base32()
    db_auth.enable_mfa(user["id"], secret)
    assert db_auth.is_mfa_enabled(user["id"]) is True


def test_disable_mfa_clears_secret(tmp_db):
    """disable_mfa flips is_mfa_enabled back to False."""
    user = _make_user(tmp_db)
    secret = pyotp.random_base32()
    db_auth.enable_mfa(user["id"], secret)
    assert db_auth.is_mfa_enabled(user["id"]) is True
    db_auth.disable_mfa(user["id"])
    assert db_auth.is_mfa_enabled(user["id"]) is False


def test_verify_totp_accepts_current_code(tmp_db):
    """A freshly-minted pyotp.TOTP.now() code must validate."""
    user = _make_user(tmp_db)
    secret = pyotp.random_base32()
    db_auth.enable_mfa(user["id"], secret)
    current = pyotp.TOTP(secret).now()
    assert db_auth.verify_totp(user["id"], current) is True


def test_verify_totp_rejects_wrong_code(tmp_db):
    """A static obviously-wrong code (000000) never validates."""
    user = _make_user(tmp_db)
    secret = pyotp.random_base32()
    db_auth.enable_mfa(user["id"], secret)
    assert db_auth.verify_totp(user["id"], "000000") is False


def test_verify_totp_returns_false_when_mfa_disabled(tmp_db):
    """verify_totp on a user without an enrolled secret returns False, not error."""
    user = _make_user(tmp_db)
    # Never called enable_mfa — mfa_secret is NULL.
    assert db_auth.verify_totp(user["id"], "123456") is False
