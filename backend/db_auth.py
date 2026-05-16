"""Auth/RBAC data layer: tenants, users, workspaces, members, API keys.

This module mirrors the style of :mod:`backend.database` — synchronous psycopg2
on top of the same :func:`backend.database.get_db` connection pool, returning
plain ``dict`` rows (``RealDictCursor``). It is intentionally *not* wired into
any FastAPI router; the route/dependency layer will be built on top of it in
Wave 2.

See ``docs/ARCHITECTURE`` §2.2 (schema) and §2.3 (RBAC).
"""

from __future__ import annotations

import datetime
import hashlib
import secrets
import uuid
from typing import Any

import psycopg2.extras
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .database import get_db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_ROLES: frozenset[str] = frozenset(
    {"owner", "admin", "editor", "launcher", "viewer"}
)

# Single shared hasher: argon2-cffi recommends reusing one instance.
_HASHER = PasswordHasher()

# Plaintext token shape: a single URL-safe random blob. We hash with SHA-256
# for lookup (constant work, no need for KDF on a 256-bit random secret).
_TOKEN_BYTES = 32


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_dt() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for key, val in list(out.items()):
        if isinstance(val, uuid.UUID):
            out[key] = str(val)
        elif isinstance(val, datetime.datetime):
            out[key] = val.isoformat()
    return out


def _require_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise ValueError(
            f"invalid role {role!r}; must be one of {sorted(VALID_ROLES)}"
        )


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Return an argon2id hash of ``password`` using the library defaults."""
    return _HASHER.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time-ish password verify. Returns ``False`` on any mismatch."""
    try:
        return _HASHER.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:
        # Defensive: never let an argon2 internal error become a 500 for callers
        # that just want to know "is this password right?".
        return False


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------


def create_tenant(name: str, plan_id: str = "free") -> dict[str, Any]:
    tenant_id = str(uuid.uuid4())
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO tenants (id, name, plan_id)
                   VALUES (%s, %s, %s)
                   RETURNING *""",
                (tenant_id, name, plan_id),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


def get_tenant(tenant_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM tenants WHERE id = %s", (tenant_id,))
            return _row_to_dict(cur.fetchone())


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def create_user(
    tenant_id: str, email: str, password: str
) -> dict[str, Any]:
    user_id = str(uuid.uuid4())
    normalized = _normalize_email(email)
    pw_hash = hash_password(password)
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO users (id, tenant_id, email, password_hash)
                   VALUES (%s, %s, %s, %s)
                   RETURNING *""",
                (user_id, tenant_id, normalized, pw_hash),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


def get_user(user_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return _row_to_dict(cur.fetchone())


def get_user_by_email(email: str) -> dict[str, Any] | None:
    normalized = _normalize_email(email)
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM users WHERE lower(email) = %s LIMIT 1",
                (normalized,),
            )
            return _row_to_dict(cur.fetchone())


def update_user_password(user_id: str, new_password: str) -> bool:
    pw_hash = hash_password(new_password)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users
                   SET password_hash = %s, updated_at = now()
                   WHERE id = %s""",
                (pw_hash, user_id),
            )
            updated = cur.rowcount > 0
        conn.commit()
    return updated


def set_email_verified(user_id: str) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users
                   SET email_verified_at = now(), updated_at = now()
                   WHERE id = %s""",
                (user_id,),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------


def create_workspace(
    tenant_id: str, name: str, owner_user_id: str
) -> dict[str, Any]:
    workspace_id = str(uuid.uuid4())
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO workspaces (id, tenant_id, name, owner_user_id)
                   VALUES (%s, %s, %s, %s)
                   RETURNING *""",
                (workspace_id, tenant_id, name, owner_user_id),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)  # type: ignore[return-value]


def get_workspace(workspace_id: str) -> dict[str, Any] | None:
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM workspaces WHERE id = %s", (workspace_id,)
            )
            return _row_to_dict(cur.fetchone())


def list_workspaces_for_user(user_id: str) -> list[dict[str, Any]]:
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT w.*, m.role AS member_role
                   FROM workspaces w
                   JOIN workspace_members m ON m.workspace_id = w.id
                   WHERE m.user_id = %s
                   ORDER BY w.created_at ASC""",
                (user_id,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]  # type: ignore[misc]


def add_workspace_member(
    workspace_id: str, user_id: str, role: str
) -> None:
    _require_role(role)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO workspace_members (workspace_id, user_id, role)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (workspace_id, user_id)
                   DO UPDATE SET role = EXCLUDED.role""",
                (workspace_id, user_id, role),
            )
        conn.commit()


def remove_workspace_member(workspace_id: str, user_id: str) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """DELETE FROM workspace_members
                   WHERE workspace_id = %s AND user_id = %s""",
                (workspace_id, user_id),
            )
            removed = cur.rowcount > 0
        conn.commit()
    return removed


def get_member_role(workspace_id: str, user_id: str) -> str | None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT role FROM workspace_members
                   WHERE workspace_id = %s AND user_id = %s""",
                (workspace_id, user_id),
            )
            row = cur.fetchone()
            return row[0] if row else None


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------


def create_api_key(
    user_id: str,
    name: str,
    scopes: list[str] | None = None,
) -> tuple[dict[str, Any], str]:
    """Create an API key for ``user_id``.

    Returns ``(record, plaintext_token)``. The plaintext is shown ONCE to the
    caller; only the SHA-256 hash is persisted in ``user_api_keys.key_hash``.
    """
    key_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    key_hash = _hash_token(token)
    effective_scopes = scopes if scopes is not None else ["*"]
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO user_api_keys
                       (id, user_id, key_hash, name, scopes)
                   VALUES (%s, %s, %s, %s, %s)
                   RETURNING *""",
                (key_id, user_id, key_hash, name, effective_scopes),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row), token  # type: ignore[return-value]


def get_api_key_by_token(token: str) -> dict[str, Any] | None:
    """Look up an active API key by its plaintext token.

    Returns ``None`` if the token is unknown OR if the key has been revoked.
    Also updates ``last_used_at`` as a side effect on a successful lookup.
    """
    key_hash = _hash_token(token)
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """UPDATE user_api_keys
                   SET last_used_at = now()
                   WHERE key_hash = %s AND revoked_at IS NULL
                   RETURNING *""",
                (key_hash,),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row)


def revoke_api_key(api_key_id: str) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE user_api_keys
                   SET revoked_at = now()
                   WHERE id = %s AND revoked_at IS NULL""",
                (api_key_id,),
            )
            revoked = cur.rowcount > 0
        conn.commit()
    return revoked


# ---------------------------------------------------------------------------
# Convenience: bootstrap a new tenant + first user + default workspace.
# ---------------------------------------------------------------------------


def signup(
    email: str,
    password: str,
    tenant_name: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Create a tenant, its first user, and a default workspace owned by them.

    Returns ``(tenant, user, workspace)``. Caller is responsible for any further
    onboarding (email verification, MFA enrolment, etc.).
    """
    normalized_email = _normalize_email(email)
    derived_tenant_name = tenant_name or normalized_email.split("@", 1)[0]

    tenant = create_tenant(derived_tenant_name)
    user = create_user(tenant["id"], normalized_email, password)
    workspace = create_workspace(tenant["id"], "Default", user["id"])
    add_workspace_member(workspace["id"], user["id"], "owner")
    return tenant, user, workspace
