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
    """Run Alembic ``upgrade head`` once per test session against DATABASE_URL."""
    _require_database_url()

    # Lazy import: alembic is only needed when tests actually run.
    from alembic import command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    # env.py reads DATABASE_URL from env; alembic.ini's script_location is
    # relative to the ini file directory, which is backend_dir.
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(cfg, "head")
    yield


def _truncate_all() -> None:
    """Wipe profile data so each test starts from a known empty state."""
    with db.get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE profile_tags, profiles RESTART IDENTITY CASCADE")
        conn.commit()


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide a clean Postgres-backed DB for the test.

    Returns the temp directory used as ``DATA_DIR`` so callers that inspect
    ``user_data_dir`` paths still work. The previous SQLite-era fixture
    returned the same kind of ``Path``; we preserve that contract.
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
