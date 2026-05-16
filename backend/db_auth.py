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


def update_workspace_member_role(
    workspace_id: str, user_id: str, role: str
) -> bool:
    """Update the role of an existing workspace member.

    Returns ``True`` if a row was updated, ``False`` if no membership exists
    for ``(workspace_id, user_id)``. Raises ``ValueError`` for invalid roles.
    """
    _require_role(role)
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE workspace_members
                   SET role = %s
                   WHERE workspace_id = %s AND user_id = %s""",
                (role, workspace_id, user_id),
            )
            updated = cur.rowcount > 0
        conn.commit()
    return updated


def count_workspace_owners(workspace_id: str) -> int:
    """Return how many members of ``workspace_id`` hold the ``owner`` role."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT count(*) FROM workspace_members
                   WHERE workspace_id = %s AND role = 'owner'""",
                (workspace_id,),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0


def list_workspace_members(workspace_id: str) -> list[dict[str, Any]]:
    """List members of a workspace with joined user email.

    Each row contains ``user_id``, ``email``, ``role``, ``created_at``.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT m.user_id, u.email, m.role, m.created_at
                   FROM workspace_members m
                   JOIN users u ON u.id = m.user_id
                   WHERE m.workspace_id = %s
                   ORDER BY m.created_at ASC""",
                (workspace_id,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]  # type: ignore[misc]


def get_user_by_email_in_tenant(
    tenant_id: str, email: str
) -> dict[str, Any] | None:
    """Look up a user by email scoped to a tenant (case-insensitive)."""
    normalized = _normalize_email(email)
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM users
                   WHERE tenant_id = %s AND lower(email) = %s
                   LIMIT 1""",
                (tenant_id, normalized),
            )
            return _row_to_dict(cur.fetchone())


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


# ---------------------------------------------------------------------------
# MFA (TOTP)
# ---------------------------------------------------------------------------


def enable_mfa(user_id: str, secret: str) -> None:
    """Persist a TOTP secret for ``user_id``, marking MFA as enabled.

    Caller is responsible for verifying the secret against a code first.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users
                   SET mfa_secret = %s, updated_at = now()
                   WHERE id = %s""",
                (secret, user_id),
            )
        conn.commit()


def disable_mfa(user_id: str) -> None:
    """Clear the TOTP secret for ``user_id``."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users
                   SET mfa_secret = NULL, updated_at = now()
                   WHERE id = %s""",
                (user_id,),
            )
        conn.commit()


def is_mfa_enabled(user_id: str) -> bool:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT mfa_secret FROM users WHERE id = %s", (user_id,)
            )
            row = cur.fetchone()
            return bool(row and row[0])


def verify_totp(user_id: str, code: str) -> bool:
    """Verify ``code`` against the user's stored TOTP secret.

    Returns ``False`` if MFA is not enabled, the code is malformed, or the
    code does not validate within a one-step window.
    """
    if not code:
        return False
    import pyotp

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT mfa_secret FROM users WHERE id = %s", (user_id,)
            )
            row = cur.fetchone()
    if not row or not row[0]:
        return False
    try:
        return bool(pyotp.TOTP(row[0]).verify(code, valid_window=1))
    except Exception:
        return False


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


# ---------------------------------------------------------------------------
# Email verification tokens (migration 0011)
#
# One-shot tokens emailed at signup / resend. The plaintext blob is only
# returned from ``create_email_verification_token`` so the caller can stitch
# it into the verification URL — only its SHA-256 lives in the table, same
# pattern as ``user_api_keys.key_hash`` above.
# ---------------------------------------------------------------------------


def create_email_verification_token(
    user_id: str, ttl_hours: int = 24
) -> tuple[dict[str, Any], str]:
    """Mint a fresh verification token for ``user_id``.

    Returns ``(record, plaintext_token)``. The plaintext is shown ONCE to the
    caller (so it can be emailed) and never persisted.
    """
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    token_hash = _hash_token(token)
    token_id = str(uuid.uuid4())
    expires_at = _now_dt() + datetime.timedelta(hours=ttl_hours)
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO email_verification_tokens
                       (id, user_id, token_hash, expires_at)
                   VALUES (%s, %s, %s, %s)
                   RETURNING *""",
                (token_id, user_id, token_hash, expires_at),
            )
            row = cur.fetchone()
        conn.commit()
    return _row_to_dict(row), token  # type: ignore[return-value]


def consume_email_verification_token(token: str) -> str | None:
    """Verify ``token``, mark it used, return its ``user_id`` on success.

    Returns ``None`` if the token is unknown, expired, or already consumed —
    callers should treat all three identically (a generic "invalid link"
    response) so we don't leak whether a token ever existed.
    """
    token_hash = _hash_token(token)
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, user_id FROM email_verification_tokens
                   WHERE token_hash = %s
                     AND used_at IS NULL
                     AND expires_at > now()""",
                (token_hash,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                """UPDATE email_verification_tokens
                   SET used_at = now()
                   WHERE id = %s""",
                (row["id"],),
            )
        conn.commit()
    return str(row["user_id"])


# ---------------------------------------------------------------------------
# OAuth (Phase 1 task WW)
#
# These helpers back the OAuth callback in :mod:`backend.routers.auth`. They
# layer on top of the regular tenant/user/workspace primitives above so the
# OAuth path produces the exact same row shapes the rest of the app expects
# — only the ``oauth_provider`` / ``oauth_provider_user_id`` columns added in
# migration 0010 distinguish an OAuth user from a password user.
#
# An OAuth user still has a NOT NULL ``password_hash`` (the schema requires
# it). We persist a hash of a fresh random secret that nobody knows; the
# password login path cannot succeed for them because :func:`verify_password`
# is only ever called with user-supplied input. This avoids relaxing the NOT
# NULL constraint, which would weaken the invariant that password-mode users
# always have a verifiable hash.
# ---------------------------------------------------------------------------


def get_user_by_oauth(
    provider: str, provider_user_id: str
) -> dict[str, Any] | None:
    """Look up the user previously linked to ``(provider, provider_user_id)``.

    Returns ``None`` if no such link exists; the caller then decides whether
    to link the OAuth identity to an existing email-match user or to mint a
    fresh tenant + user via :func:`signup_oauth`.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM users
                   WHERE oauth_provider = %s
                     AND oauth_provider_user_id = %s
                   LIMIT 1""",
                (provider, provider_user_id),
            )
            return _row_to_dict(cur.fetchone())


def link_oauth(
    user_id: str, provider: str, provider_user_id: str
) -> None:
    """Attach an OAuth identity to an existing user row.

    Called when an OAuth callback resolves to an email that already has a
    password-mode account — we link rather than reject so users don't end up
    with two accounts for the same email address. The partial unique index
    on ``(oauth_provider, oauth_provider_user_id)`` prevents a single IdP
    identity from being linked to two users.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE users
                   SET oauth_provider = %s,
                       oauth_provider_user_id = %s,
                       updated_at = now()
                   WHERE id = %s""",
                (provider, provider_user_id, user_id),
            )
        conn.commit()


def signup_oauth(
    provider: str,
    provider_user_id: str,
    email: str,
    name: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Provision a brand-new tenant + user + workspace from an OAuth identity.

    Mirrors :func:`signup` but:

    * The password column is filled with an argon2 hash of a fresh random
      secret nobody possesses — keeps the NOT NULL invariant intact while
      ensuring the password login path can never authenticate this user.
    * The OAuth identity columns are set in the same INSERT to avoid a
      window in which a user row exists without its IdP link (which would
      let a parallel OAuth callback for the same identity create a
      duplicate row before :func:`get_user_by_oauth` would see it).
    * ``email_verified_at`` is stamped to ``now()`` — the IdP has already
      proven the user controls the address.
    """
    normalized_email = _normalize_email(email)
    derived_tenant_name = name or normalized_email.split("@", 1)[0]

    tenant = create_tenant(derived_tenant_name)
    # Inline user creation so we can set OAuth columns + email_verified_at
    # in the same INSERT — avoids the two-step race noted above.
    user_id = str(uuid.uuid4())
    unusable_password_hash = hash_password(secrets.token_urlsafe(32))
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """INSERT INTO users
                       (id, tenant_id, email, password_hash,
                        oauth_provider, oauth_provider_user_id,
                        email_verified_at)
                   VALUES (%s, %s, %s, %s, %s, %s, now())
                   RETURNING *""",
                (
                    user_id,
                    tenant["id"],
                    normalized_email,
                    unusable_password_hash,
                    provider,
                    provider_user_id,
                ),
            )
            user_row = cur.fetchone()
        conn.commit()
    user = _row_to_dict(user_row)  # type: ignore[arg-type]
    assert user is not None  # just inserted
    workspace = create_workspace(tenant["id"], "Default", user["id"])
    add_workspace_member(workspace["id"], user["id"], "owner")
    return tenant, user, workspace
