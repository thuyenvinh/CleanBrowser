"""Tests for ``require_verified_email`` dependency (M5).

The gate blocks sensitive actions (invite, API-key mint, checkout) until
the user has clicked the verification link. Implementation lives in
:mod:`backend.dependencies` and runs as a FastAPI ``Depends``; we exercise
it inline as a plain function call to avoid spinning up a TestClient.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.dependencies import require_verified_email


def test_require_verified_email_blocks_unverified():
    """``email_verified_at=None`` → 403."""
    user = {"id": "x", "email": "x@x", "email_verified_at": None}
    with pytest.raises(HTTPException) as ei:
        require_verified_email(user)
    assert ei.value.status_code == 403


def test_require_verified_email_allows_verified():
    """A timestamp in ``email_verified_at`` lets the user through unchanged."""
    user = {
        "id": "x",
        "email": "x@x",
        "email_verified_at": "2025-01-01T00:00:00Z",
    }
    result = require_verified_email(user)
    assert result is user


def test_require_verified_email_detail_carries_marker():
    """Detail body includes ``error: 'email_not_verified'`` so the client can branch."""
    user = {"id": "x", "email": "x@x", "email_verified_at": None}
    with pytest.raises(HTTPException) as ei:
        require_verified_email(user)
    # detail may be a dict or a string repr depending on how FastAPI handles
    # it — stringifying always works.
    assert "email_not_verified" in str(ei.value.detail)


def test_require_verified_email_blocks_missing_key():
    """A user dict without the key at all is treated as unverified."""
    user = {"id": "x", "email": "x@x"}
    with pytest.raises(HTTPException) as ei:
        require_verified_email(user)
    assert ei.value.status_code == 403
