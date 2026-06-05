"""Tests for the C7 fix: profile delete is restricted to creator or admin+.

The router-private helper ``_check_mutation_permission`` enforces:
    * legacy / unauthenticated callers (``user is None``) bypass entirely;
    * the creator (``created_by_user_id``) can always mutate;
    * other workspace members need admin+ (editors are NOT enough — that
      was the bug).

We hit the helper directly (it's plain logic against db_auth.get_member_role)
rather than wire up a TestClient, mirroring the unit-test style elsewhere
in this suite.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from backend import database as db, db_auth
from backend.routers.profiles import _check_mutation_permission


def _make_user(tmp_db, prefix: str = "owner") -> dict:
    _, user, ws = db_auth.signup(
        email=f"{prefix}+{uuid.uuid4().hex[:8]}@example.test",
        password="password123",
    )
    user["workspace_id"] = ws["id"]
    user["tenant_id"] = ws["tenant_id"]
    return user


def _add_peer_to_workspace(
    tmp_db, workspace_id: str, role: str, prefix: str = "peer"
) -> dict:
    """Create a second user and add them to ``workspace_id`` with ``role``.

    Used to test the cross-member matrix: editor / admin / etc. We sign up
    a brand new tenant for them and then graft them onto the host workspace
    as a member at the requested role.
    """
    _, peer, _ = db_auth.signup(
        email=f"{prefix}+{uuid.uuid4().hex[:8]}@example.test",
        password="password123",
    )
    db_auth.add_workspace_member(workspace_id, peer["id"], role)
    return peer


def test_creator_can_mutate_own_profile(tmp_db):
    """Creator passes the C7 check trivially via the ownership branch."""
    owner = _make_user(tmp_db)
    profile = db.create_profile(
        name="owned",
        workspace_id=owner["workspace_id"],
        created_by_user_id=owner["id"],
    )
    # Should not raise.
    _check_mutation_permission(profile, owner)


def test_editor_peer_cannot_mutate_others_profile(tmp_db):
    """Editor in same workspace, not the creator → 403 by C7 fix."""
    owner = _make_user(tmp_db, prefix="creator")
    editor_peer = _add_peer_to_workspace(
        tmp_db, owner["workspace_id"], "editor", prefix="editor"
    )
    profile = db.create_profile(
        name="owned-by-creator",
        workspace_id=owner["workspace_id"],
        created_by_user_id=owner["id"],
    )
    with pytest.raises(HTTPException) as excinfo:
        _check_mutation_permission(profile, editor_peer)
    assert excinfo.value.status_code == 403


def test_admin_peer_can_mutate_others_profile(tmp_db):
    """Admin in same workspace clears the role floor even without ownership."""
    owner = _make_user(tmp_db, prefix="creator")
    admin_peer = _add_peer_to_workspace(
        tmp_db, owner["workspace_id"], "admin", prefix="admin"
    )
    profile = db.create_profile(
        name="owned-by-creator",
        workspace_id=owner["workspace_id"],
        created_by_user_id=owner["id"],
    )
    # Should not raise.
    _check_mutation_permission(profile, admin_peer)


def test_legacy_profile_null_creator_bypasses_check(tmp_db):
    """Profiles created before the column existed (``created_by_user_id IS NULL``)
    still allow deletion via the admin+ branch (or owner)."""
    owner = _make_user(tmp_db, prefix="creator")
    profile = db.create_profile(
        name="legacy",
        workspace_id=owner["workspace_id"],
        # No created_by_user_id — null.
    )
    # Owner of the workspace (role=owner) should pass admin+ check.
    _check_mutation_permission(profile, owner)


def test_unauthenticated_user_bypass(tmp_db):
    """``user is None`` is the legacy / AUTH_TOKEN bypass — no exception."""
    owner = _make_user(tmp_db)
    profile = db.create_profile(
        name="owned",
        workspace_id=owner["workspace_id"],
        created_by_user_id=owner["id"],
    )
    # Should not raise.
    _check_mutation_permission(profile, None)
