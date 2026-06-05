"""Tests for unique (workspace_id, name) constraints (H9 fix).

Two profiles or two proxies with the same name in the same workspace must
be rejected with a typed exception the route layer can convert to 409.
"""
from __future__ import annotations

import uuid

import pytest

from backend import database as db
from backend import db_proxy


def _make_workspace(tmp_db) -> str:
    from backend.database import get_db
    tenant_id = str(uuid.uuid4())
    workspace_id = str(uuid.uuid4())
    owner_id = str(uuid.uuid4())
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (id, name, plan_id, status) VALUES (%s, %s, %s, %s)",
                (tenant_id, "anti-dup", "free", "active"),
            )
            cur.execute(
                "INSERT INTO users (id, tenant_id, email, password_hash) VALUES (%s, %s, %s, %s)",
                (owner_id, tenant_id, f"u-{owner_id}@x", "argon2$x"),
            )
            cur.execute(
                "INSERT INTO workspaces (id, tenant_id, name, owner_user_id) VALUES (%s, %s, %s, %s)",
                (workspace_id, tenant_id, "ws", owner_id),
            )
    return workspace_id


def test_profile_duplicate_name_same_workspace_raises(tmp_db):
    ws_id = _make_workspace(tmp_db)
    db.create_profile(name="duplicate", workspace_id=ws_id)
    with pytest.raises(db.DuplicateProfileName):
        db.create_profile(name="duplicate", workspace_id=ws_id)


def test_profile_duplicate_name_different_workspaces_ok(tmp_db):
    ws_a = _make_workspace(tmp_db)
    ws_b = _make_workspace(tmp_db)
    db.create_profile(name="shared", workspace_id=ws_a)
    db.create_profile(name="shared", workspace_id=ws_b)  # should NOT raise


def test_profile_null_workspace_allows_duplicates(tmp_db):
    """Legacy / unauthenticated profiles (NULL workspace_id) keep working."""
    db.create_profile(name="legacy")
    db.create_profile(name="legacy")  # no error: partial index excludes NULL


def test_proxy_duplicate_name_same_workspace_raises(tmp_db):
    ws_id = _make_workspace(tmp_db)
    db_proxy.create_proxy(
        workspace_id=ws_id, name="proxy-a", type="http", host="1.1.1.1", port=8080
    )
    with pytest.raises(db_proxy.DuplicateProxyName):
        db_proxy.create_proxy(
            workspace_id=ws_id, name="proxy-a", type="http", host="2.2.2.2", port=9090
        )


def test_proxy_duplicate_name_different_workspaces_ok(tmp_db):
    ws_a = _make_workspace(tmp_db)
    ws_b = _make_workspace(tmp_db)
    db_proxy.create_proxy(
        workspace_id=ws_a, name="rotating", type="http", host="1.1.1.1", port=8080
    )
    db_proxy.create_proxy(
        workspace_id=ws_b, name="rotating", type="http", host="2.2.2.2", port=9090
    )
