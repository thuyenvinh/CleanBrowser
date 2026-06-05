"""Tests for workspace rename / delete + last-owner protection (H4).

Covers the data-layer helpers exercised by ``PATCH /workspaces/{id}`` and
``DELETE /workspaces/{id}``. The HTTP layer also enforces a
"last workspace per user" guard which is reproduced inline here without
going through TestClient — keeps the test focused on the contract.
"""
from __future__ import annotations

import uuid

from backend import db_auth


def _make_user(prefix: str = "ws") -> tuple[dict, dict, dict]:
    return db_auth.signup(
        email=f"{prefix}+{uuid.uuid4().hex[:8]}@example.test",
        password="some-secure-password",
    )


def test_update_workspace_name_success(tmp_db):
    """``update_workspace_name`` returns the updated row with the new name."""
    _, user, ws = _make_user("rename")
    updated = db_auth.update_workspace_name(ws["id"], "renamed-ws")
    assert updated is not None
    assert updated["name"] == "renamed-ws"
    assert updated["id"] == ws["id"]
    # Fetch fresh to confirm the rename was committed.
    fetched = db_auth.get_workspace(ws["id"])
    assert fetched["name"] == "renamed-ws"


def test_delete_workspace_success(tmp_db):
    """``delete_workspace`` returns True and removes the row."""
    _, user, ws = _make_user("delete")
    # Create a *second* workspace so the user isn't left orphaned post-delete
    # — purely a realism touch, the data-layer fn itself doesn't enforce that.
    second = db_auth.create_workspace(user["tenant_id"], "second", user["id"])
    db_auth.add_workspace_member(second["id"], user["id"], "owner")

    removed = db_auth.delete_workspace(ws["id"])
    assert removed is True
    assert db_auth.get_workspace(ws["id"]) is None
    # Second workspace is untouched.
    assert db_auth.get_workspace(second["id"]) is not None


def test_count_workspace_owners_counts_correctly(tmp_db):
    """Owner count reflects only members with role='owner'."""
    _, owner, ws = _make_user("owners")
    # Fresh workspace from signup has exactly one owner.
    assert db_auth.count_workspace_owners(ws["id"]) == 1

    # Add a second user as 'viewer' — count stays at 1.
    _, member_user, _ = _make_user("member")
    db_auth.add_workspace_member(ws["id"], member_user["id"], "viewer")
    assert db_auth.count_workspace_owners(ws["id"]) == 1

    # Promote them to owner — count climbs to 2.
    db_auth.update_workspace_member_role(ws["id"], member_user["id"], "owner")
    assert db_auth.count_workspace_owners(ws["id"]) == 2


def test_last_owner_protection_via_count(tmp_db):
    """Reject removing the last owner; mirrors the router-level guard.

    Doesn't go through HTTP — replays the same ``count_workspace_owners <= 1``
    check the router uses before calling ``remove_workspace_member``.
    """
    _, owner, ws = _make_user("lastowner")

    def safe_remove(workspace_id: str, user_id: str) -> bool:
        # Router refuses to demote / kick the final owner.
        if db_auth.count_workspace_owners(workspace_id) <= 1:
            return False
        return db_auth.remove_workspace_member(workspace_id, user_id)

    assert safe_remove(ws["id"], owner["id"]) is False
    # The original owner is still present.
    assert db_auth.get_member_role(ws["id"], owner["id"]) == "owner"

    # Now add another owner so removing the first becomes legal.
    _, second_owner, _ = _make_user("second")
    db_auth.add_workspace_member(ws["id"], second_owner["id"], "owner")
    assert safe_remove(ws["id"], owner["id"]) is True
    assert db_auth.get_member_role(ws["id"], owner["id"]) is None


def test_cannot_delete_only_workspace_per_user(tmp_db):
    """Mirror the router guard: ``len(list_workspaces_for_user) <= 1`` blocks delete."""
    _, user, ws = _make_user("only")
    # signup gives the user exactly one workspace.
    assert len(db_auth.list_workspaces_for_user(user["id"])) == 1

    def safe_delete(user_id: str, workspace_id: str) -> bool:
        owned = db_auth.list_workspaces_for_user(user_id)
        if len(owned) <= 1:
            return False
        return db_auth.delete_workspace(workspace_id)

    assert safe_delete(user["id"], ws["id"]) is False
    assert db_auth.get_workspace(ws["id"]) is not None

    # After creating a second workspace, the guard releases.
    second = db_auth.create_workspace(user["tenant_id"], "second", user["id"])
    db_auth.add_workspace_member(second["id"], user["id"], "owner")
    assert safe_delete(user["id"], ws["id"]) is True
    assert db_auth.get_workspace(ws["id"]) is None
