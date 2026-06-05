"""Proxy pool data layer.

Workspace-scoped CRUD for the ``proxies`` table introduced by migration
``0006_add_proxies``. Mirrors the style of :mod:`backend.db_auth` —
synchronous psycopg2 on top of :func:`backend.database.get_db`, returning
plain ``dict`` rows. Intentionally NOT wired into any router / launch flow;
adoption happens in a later Phase 2 task.

Credential handling
-------------------
Passwords are stored Fernet-encrypted in ``proxies.password_enc``. The key
comes from the ``PROXY_ENCRYPTION_KEY`` env var (44-char urlsafe base64,
i.e. the output of :meth:`cryptography.fernet.Fernet.generate_key`). If the
env var is missing, a per-process key is generated and a *loud* warning is
emitted — encrypted rows written in dev will be unreadable after a restart,
which is the correct behaviour (never silently fall back to a static key in
production).

The cipher is initialised lazily on first encrypt/decrypt so that importing
this module never raises at process start (e.g. during ``alembic upgrade``).

See ``docs/ARCHITECTURE`` §2.5.
"""

from __future__ import annotations

import datetime
import logging
import os
import threading
import uuid
from typing import Any
from urllib.parse import quote

import psycopg2
import psycopg2.extras
from cryptography.fernet import Fernet, InvalidToken

from .database import get_db


class DuplicateProxyName(ValueError):
    """Raised when create_proxy / update_proxy would violate the
    ``ux_proxies_workspace_name`` unique index (migration 0029).

    Subclasses :class:`ValueError` so the existing ``except ValueError``
    handler in ``routers/proxies.py`` surfaces it as 400 automatically. See
    heuristic H9.
    """

logger = logging.getLogger("cloakbrowser.proxy")


# ---------------------------------------------------------------------------
# Constants / validation
# ---------------------------------------------------------------------------

VALID_TYPES: frozenset[str] = frozenset({"http", "https", "socks5"})
VALID_STATUSES: frozenset[str] = frozenset({"ok", "fail", "unchecked"})

# Columns the app layer is allowed to update via ``update_proxy(**fields)``.
# ``password`` is handled separately (plaintext IN → ``password_enc`` OUT).
_UPDATABLE_COLUMNS: frozenset[str] = frozenset(
    {
        "name",
        "type",
        "host",
        "port",
        "username",
        "provider",
        "rotation_url",
        "sticky_session",
        "country_code",
    }
)


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

_fernet: Fernet | None = None
_fernet_lock = threading.Lock()


def _load_fernet() -> Fernet:
    """Return a process-wide Fernet, loading the key on first call.

    Resolution order:
      1. ``PROXY_ENCRYPTION_KEY`` env var (44-char urlsafe base64).
      2. Fall back to a freshly generated per-process key + WARN. Tokens
         written under the fallback do NOT survive a process restart.
    """
    global _fernet
    if _fernet is not None:
        return _fernet
    with _fernet_lock:
        if _fernet is not None:
            return _fernet
        key = os.environ.get("PROXY_ENCRYPTION_KEY")
        if key:
            try:
                _fernet = Fernet(key.encode("utf-8"))
            except (ValueError, TypeError) as exc:
                # Invalid key shape — refuse to silently degrade.
                raise RuntimeError(
                    "PROXY_ENCRYPTION_KEY is set but not a valid Fernet key "
                    "(expected 44-char urlsafe base64): " + str(exc)
                ) from exc
        else:
            fallback = Fernet.generate_key()
            logger.warning(
                "PROXY_ENCRYPTION_KEY is not set — generated an ephemeral "
                "per-process key. Proxy passwords stored now will be "
                "UNREADABLE after a restart. Set PROXY_ENCRYPTION_KEY in "
                "production (output of cryptography.fernet.Fernet."
                "generate_key())."
            )
            _fernet = Fernet(fallback)
        return _fernet


def _encrypt(s: str | None) -> str | None:
    """Fernet-encrypt ``s``. ``None`` passes through."""
    if s is None:
        return None
    token = _load_fernet().encrypt(s.encode("utf-8"))
    return token.decode("utf-8")


def _decrypt(s: str | None) -> str | None:
    """Fernet-decrypt ``s``. ``None`` passes through.

    Raises :class:`cryptography.fernet.InvalidToken` if the ciphertext is
    corrupt or was encrypted under a different key (e.g. an old ephemeral
    fallback). Callers needing tolerance can catch this.
    """
    if s is None:
        return None
    plain = _load_fernet().decrypt(s.encode("utf-8"))
    return plain.decode("utf-8")


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def _require_type(type_: str) -> None:
    if type_ not in VALID_TYPES:
        raise ValueError(
            f"invalid proxy type {type_!r}; must be one of {sorted(VALID_TYPES)}"
        )


def _require_status(status: str) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(
            f"invalid proxy status {status!r}; must be one of "
            f"{sorted(VALID_STATUSES)}"
        )


def _require_port(port: int) -> None:
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise ValueError(f"invalid port {port!r}; must be int in 1..65535")


def _row_to_dict(
    row: Any, *, decrypt_password: bool = False
) -> dict[str, Any] | None:
    """Normalise a psycopg2 RealDict row for JSON serialisation.

    Stringifies UUIDs / datetimes (parity with :mod:`db_auth`) and, by
    default, strips ``password_enc`` so it never leaks into API responses.
    With ``decrypt_password=True`` the field is replaced by a plaintext
    ``password`` key — intended for internal use only (e.g.
    :func:`build_proxy_url`).
    """
    if row is None:
        return None
    out = dict(row)
    for key, val in list(out.items()):
        if isinstance(val, uuid.UUID):
            out[key] = str(val)
        elif isinstance(val, datetime.datetime):
            out[key] = val.isoformat()
    if decrypt_password:
        enc = out.pop("password_enc", None)
        out["password"] = _decrypt(enc) if enc is not None else None
    else:
        out.pop("password_enc", None)
    return out


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_proxy(
    workspace_id: str,
    name: str,
    type: str,
    host: str,
    port: int,
    username: str | None = None,
    password: str | None = None,
    provider: str = "manual",
    rotation_url: str | None = None,
    sticky_session: str | None = None,
    country_code: str | None = None,
) -> dict[str, Any]:
    """Insert a proxy row, returning the persisted record (no ``password_enc``).

    ``password`` is the *plaintext* — it is Fernet-encrypted into
    ``password_enc`` before the INSERT and is never logged.
    """
    _require_type(type)
    _require_port(port)

    proxy_id = str(uuid.uuid4())
    password_enc = _encrypt(password)

    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO proxies (
                        id, workspace_id, name, type, host, port,
                        username, password_enc, provider, rotation_url,
                        sticky_session, country_code
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s
                    ) RETURNING *""",
                    (
                        proxy_id,
                        workspace_id,
                        name,
                        type,
                        host,
                        port,
                        username,
                        password_enc,
                        provider,
                        rotation_url,
                        sticky_session,
                        country_code,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
    except psycopg2.errors.UniqueViolation as exc:
        # H9 — workspace-scoped duplicate name guard (migration 0029).
        if "ux_proxies_workspace_name" in str(exc):
            raise DuplicateProxyName(
                f"A proxy named {name!r} already exists in this workspace"
            ) from exc
        raise
    return _row_to_dict(row)  # type: ignore[return-value]


def get_proxy(
    proxy_id: str, decrypt_password: bool = False
) -> dict[str, Any] | None:
    """Fetch one proxy by id.

    ``decrypt_password=True`` exposes a plaintext ``password`` key (used by
    :func:`build_proxy_url`). The default strips ``password_enc`` entirely
    so the row is safe to serialise.
    """
    try:
        uuid.UUID(str(proxy_id))
    except (ValueError, AttributeError, TypeError):
        return None
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM proxies WHERE id = %s", (proxy_id,))
            row = cur.fetchone()
    return _row_to_dict(row, decrypt_password=decrypt_password)


def list_proxies(
    workspace_id: str, status: str | None = None
) -> list[dict[str, Any]]:
    """List a workspace's proxies, optionally filtered by health ``status``."""
    if status is not None:
        _require_status(status)
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if status is None:
                cur.execute(
                    """SELECT * FROM proxies
                       WHERE workspace_id = %s
                       ORDER BY created_at ASC""",
                    (workspace_id,),
                )
            else:
                cur.execute(
                    """SELECT * FROM proxies
                       WHERE workspace_id = %s AND status = %s
                       ORDER BY created_at ASC""",
                    (workspace_id, status),
                )
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


def update_proxy(proxy_id: str, **fields: Any) -> dict[str, Any] | None:
    """Patch a proxy row. Unknown columns are silently ignored.

    Special-cased keys:
      * ``password`` (plaintext) → encrypted into ``password_enc``. Pass
        ``password=None`` to clear the stored credential.
      * ``type`` / ``port`` → validated, raise ``ValueError`` on bad input.

    Returns the updated record (``password_enc`` stripped) or ``None`` if
    no row matched ``proxy_id``.
    """
    try:
        uuid.UUID(str(proxy_id))
    except (ValueError, AttributeError, TypeError):
        return None
    if not fields:
        return get_proxy(proxy_id)

    update_cols: list[str] = []
    update_vals: list[Any] = []

    if "type" in fields:
        _require_type(fields["type"])
    if "port" in fields:
        _require_port(fields["port"])

    for col in _UPDATABLE_COLUMNS:
        if col in fields:
            update_cols.append(f"{col} = %s")
            update_vals.append(fields[col])

    if "password" in fields:
        update_cols.append("password_enc = %s")
        update_vals.append(_encrypt(fields["password"]))

    if not update_cols:
        return get_proxy(proxy_id)

    update_cols.append("updated_at = now()")
    update_vals.append(proxy_id)

    try:
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    f"UPDATE proxies SET {', '.join(update_cols)} "
                    f"WHERE id = %s RETURNING *",
                    update_vals,
                )
                row = cur.fetchone()
            conn.commit()
    except psycopg2.errors.UniqueViolation as exc:
        # H9 — same guard applies to rename via update.
        if "ux_proxies_workspace_name" in str(exc):
            raise DuplicateProxyName(
                f"A proxy named {fields.get('name')!r} already exists "
                "in this workspace"
            ) from exc
        raise
    return _row_to_dict(row)


def delete_proxy(proxy_id: str) -> bool:
    """Hard-delete a proxy row. Returns ``True`` if a row was deleted."""
    try:
        uuid.UUID(str(proxy_id))
    except (ValueError, AttributeError, TypeError):
        return False
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM proxies WHERE id = %s", (proxy_id,))
            rowcount = cur.rowcount
        conn.commit()
    return rowcount > 0


def update_proxy_health(
    proxy_id: str,
    status: str,
    latency_ms: int | None = None,
    last_error: str | None = None,
    country_code: str | None = None,
) -> None:
    """Record the outcome of a health probe.

    ``last_check_at`` is set to ``now()`` server-side. ``country_code`` is
    only overwritten when a non-``None`` value is passed (so the GeoIP
    auto-detect on first OK probe doesn't get wiped by later probes that
    didn't re-resolve).
    """
    _require_status(status)
    set_cols: list[str] = [
        "status = %s",
        "latency_ms = %s",
        "last_error = %s",
        "last_check_at = now()",
        "updated_at = now()",
    ]
    vals: list[Any] = [status, latency_ms, last_error]
    if country_code is not None:
        set_cols.append("country_code = %s")
        vals.append(country_code)
    vals.append(proxy_id)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE proxies SET {', '.join(set_cols)} WHERE id = %s",
                vals,
            )
        conn.commit()


def build_proxy_url(proxy_id: str) -> str:
    """Return a fully-qualified proxy URL ready for browser launch.

    Shape: ``<type>://[user[:pass]@]host:port``. Credentials are
    URL-encoded so passwords containing ``@`` / ``:`` / ``/`` don't break
    parsing. The decrypted password is held only on the stack of this
    function and is NEVER logged — callers that need to expose the URL in
    debug output must redact it themselves.
    """
    row = get_proxy(proxy_id, decrypt_password=True)
    if row is None:
        raise KeyError(f"proxy {proxy_id!r} not found")

    scheme = row["type"]
    host = row["host"]
    port = row["port"]
    username = row.get("username")
    password = row.get("password")

    if username:
        user_part = quote(username, safe="")
        if password:
            user_part = f"{user_part}:{quote(password, safe='')}"
        return f"{scheme}://{user_part}@{host}:{port}"
    return f"{scheme}://{host}:{port}"


def list_proxies_for_check(stale_minutes: int = 5) -> list[dict[str, Any]]:
    """Return proxies whose ``last_check_at`` is NULL or older than
    ``stale_minutes``. Used by the background health worker.

    The query is cross-workspace by design — health probing is a global
    pool-maintenance concern. Rows are capped at 200 per pass to keep
    a single iteration bounded; the next pass will pick up the remainder.
    """
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT * FROM proxies
                   WHERE last_check_at IS NULL
                      OR last_check_at < now() - make_interval(mins => %s)
                   ORDER BY last_check_at NULLS FIRST
                   LIMIT 200""",
                (stale_minutes,),
            )
            rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[misc]


__all__ = [
    "VALID_TYPES",
    "VALID_STATUSES",
    "InvalidToken",
    "create_proxy",
    "get_proxy",
    "list_proxies",
    "list_proxies_for_check",
    "update_proxy",
    "delete_proxy",
    "update_proxy_health",
    "build_proxy_url",
]
