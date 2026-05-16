"""Shared test fixtures for backend tests.

Tests run against a real PostgreSQL instance pointed at by ``DATABASE_URL``.
The schema is migrated once per session via Alembic; each test gets a clean
slate by truncating the profile tables (``TRUNCATE ... CASCADE``) between
runs. No SQLite, no temp DB files.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

# ---------------------------------------------------------------------------
# Mock cloakbrowser BEFORE any backend module is imported.
# browser_manager.py does `from cloakbrowser import launch_persistent_context_async`
# at module level, and main.py imports BrowserManager which triggers it.
# main.py also does `from cloakbrowser.config import CHROMIUM_VERSION`.
# ---------------------------------------------------------------------------

_mock_cloakbrowser = types.ModuleType("cloakbrowser")
_mock_cloakbrowser.launch_persistent_context_async = AsyncMock()  # type: ignore[attr-defined]

_mock_config = types.ModuleType("cloakbrowser.config")
_mock_config.CHROMIUM_VERSION = "0.0.0-test"  # type: ignore[attr-defined]

sys.modules.setdefault("cloakbrowser", _mock_cloakbrowser)
sys.modules.setdefault("cloakbrowser.config", _mock_config)


from backend import database as db  # noqa: E402
from backend.middleware_rls import (  # noqa: E402
    SYSTEM_TENANT_ID,
    _current_tenant,
)


def _require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip(
            "DATABASE_URL is not set. Set it to a Postgres DSN, e.g. "
            "postgresql://cleanbrowser:devpassword@localhost:5432/cleanbrowser",
            allow_module_level=False,
        )
    return url


@pytest.fixture(scope="session", autouse=True)
def _migrate_schema():
    """Run Alembic ``upgrade head`` once per test session against DATABASE_URL.

    Before invoking Alembic, widen ``alembic_version.version_num`` to 255
    chars if it already exists at the legacy 32-char width. Some revisions
    in this project (e.g. ``0011_add_email_verification_tokens``, 34
    chars) overflow Alembic's default ``VARCHAR(32)`` and would trip
    ``StringDataRightTruncation`` during bookkeeping. This is the test
    suite's pre-flight fix only — production deploys handle the same
    situation in their own migration runner.
    """
    _require_database_url()

    # Lazy import: alembic is only needed when tests actually run.
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    # env.py reads DATABASE_URL from env; alembic.ini's script_location is
    # relative to the ini file directory, which is backend_dir.
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))

    # Step 1: upgrade to 0009 (last revision with a short enough id to fit
    # Alembic's default ``VARCHAR(32)`` ``version_num`` column). This
    # forces Alembic to create the bookkeeping table on first run.
    command.upgrade(cfg, "0009_add_rls")

    # Step 2: widen the column past 32 chars so the longer revision
    # identifiers (e.g. ``0011_add_email_verification_tokens``, 34
    # chars) don't trip ``StringDataRightTruncation`` during the
    # post-migration ``UPDATE alembic_version SET version_num=…``
    # bookkeeping. Idempotent — re-running against an already-widened
    # column is a no-op.
    with db.get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE alembic_version "
                "ALTER COLUMN version_num TYPE varchar(255)"
            )
        conn.commit()

    # Step 3: finish the upgrade to head, now that the column is wide
    # enough to hold every remaining revision id.
    command.upgrade(cfg, "head")
    yield


def _truncate_all() -> None:
    """Wipe profile data so each test starts from a known empty state.

    Must be called from inside a :func:`system_context` (or with the tenant
    ContextVar already pinned to :data:`SYSTEM_TENANT_ID`) — the restrictive
    RLS policies installed by migration ``0012_rls_restrictive`` block
    ``TRUNCATE`` from a connection whose ``app.current_tenant_id`` GUC is
    empty. Callers in this module satisfy that requirement via the
    ``_rls_system_bypass`` autouse fixture below.
    """
    with db.get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE profile_tags, profiles RESTART IDENTITY CASCADE")
        conn.commit()


@pytest.fixture(autouse=True)
def _rls_system_bypass():
    """Pin the RLS tenant ContextVar to :data:`SYSTEM_TENANT_ID` for every test.

    Migration ``0012_rls_restrictive`` flipped the row-level-security
    policies to restrictive so a connection with an empty
    ``app.current_tenant_id`` GUC sees zero rows. The test suite was
    written against the permissive 0009 era and exercises ``db.*`` helpers
    directly (no router, no ``get_optional_user``), so without a bypass
    every call to e.g. ``db.create_profile`` would write a row that
    immediately becomes invisible to the next ``SELECT``.

    Pinning the ContextVar here — rather than wrapping each individual
    ``db.get_db()`` call in :func:`system_context` — keeps the test code
    unchanged and matches the spirit of the previous permissive default.
    The :class:`contextvars.Token` returned by ``set`` is reset in the
    teardown so the binding never escapes the test.

    Autouse + function scope means this fires for *every* test (including
    those that don't take ``tmp_db``), which is what we want: a worker /
    middleware unit test that incidentally calls ``db.get_db`` should
    behave the same way under restrictive RLS as it did under permissive.
    """
    token = _current_tenant.set(SYSTEM_TENANT_ID)
    try:
        yield
    finally:
        _current_tenant.reset(token)


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide a clean Postgres-backed DB for the test.

    Returns the temp directory used as ``DATA_DIR`` so callers that inspect
    ``user_data_dir`` paths still work. The previous SQLite-era fixture
    returned the same kind of ``Path``; we preserve that contract.

    Truncate runs under the ``_rls_system_bypass`` autouse fixture which
    has already pinned the tenant ContextVar to :data:`SYSTEM_TENANT_ID`,
    so the RLS policies installed by 0012 allow the ``TRUNCATE`` through.
    """
    _require_database_url()
    # Reset the connection pool so a fresh pool is built bound to DATABASE_URL
    # (in case other tests/processes changed the env in this session).
    monkeypatch.setattr(db, "_POOL", None)
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)

    _truncate_all()
    db.init_db()
    yield tmp_path
    _truncate_all()


@pytest.fixture()
def sample_profile(tmp_db: Path):
    """Create and return a sample profile dict."""
    return db.create_profile(name="Test Profile", fingerprint_seed=12345)


@pytest.fixture()
def app_client(tmp_db: Path, monkeypatch: pytest.MonkeyPatch):
    """FastAPI TestClient with mocked DB and browser manager."""
    from backend import main

    # Patch lifespan-called methods to avoid subprocess calls (pkill, Xvnc)
    monkeypatch.setattr(main.browser_mgr, "cleanup_stale", AsyncMock())
    monkeypatch.setattr(main.browser_mgr, "cleanup_all", AsyncMock())
    monkeypatch.setattr(main.browser_mgr.vnc, "cleanup_stale", AsyncMock())

    from starlette.testclient import TestClient

    with TestClient(main.app) as client:
        yield client
