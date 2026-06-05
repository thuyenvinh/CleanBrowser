"""add unique name constraints for profiles & proxies per workspace

Heuristic H9 — the UI happily lets a user create five profiles called "test"
inside the same workspace, with no warning. Same story for proxies. The fix
is a workspace-scoped uniqueness guarantee at the schema layer so the
backend can't silently accept duplicates regardless of which call path
(REST, CLI script, marketplace install) created the row.

Design notes
------------
* ``profiles.workspace_id`` is NULLABLE (see migration 0005) — legacy /
  unauth rows have no workspace. A blanket ``UNIQUE (workspace_id, name)``
  would block any number of orphan rows from sharing a name once one of
  them is NULL, which Postgres treats as "all distinct" anyway, but more
  importantly we want to leave the legacy AUTH_TOKEN / test-suite flow
  alone. The partial index ``WHERE workspace_id IS NOT NULL`` enforces
  uniqueness only for the multi-tenant path.

* ``proxies.workspace_id`` is NOT NULL by construction (every proxy is
  workspace-scoped — see migration 0006), so a plain unique index is
  enough; no partial predicate needed.

* We use ``CREATE UNIQUE INDEX`` rather than ``ALTER TABLE ... ADD
  CONSTRAINT UNIQUE`` because partial-predicate uniqueness is only
  expressible via an index in Postgres.

The application layer (``backend/database.py::create_profile``,
``backend/db_proxy.py::create_proxy``) catches the resulting
``UniqueViolation`` and re-raises a typed ``ValueError`` subclass with a
human-readable message so callers (routers, scripts) can surface a clean
409-style error.

Revision ID: 0029_unique_name_per_workspace
Revises: 0028_add_profile_created_by
Create Date: 2026-06-03
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0029_unique_name_per_workspace"
down_revision: Union[str, Sequence[str], None] = "0028_add_profile_created_by"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Partial unique index: leaves legacy NULL-workspace rows alone.
    op.execute(
        "CREATE UNIQUE INDEX ux_profiles_workspace_name "
        "ON profiles(workspace_id, name) "
        "WHERE workspace_id IS NOT NULL"
    )
    # proxies.workspace_id is NOT NULL — full unique index is fine.
    op.execute(
        "CREATE UNIQUE INDEX ux_proxies_workspace_name "
        "ON proxies(workspace_id, name)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_proxies_workspace_name")
    op.execute("DROP INDEX IF EXISTS ux_profiles_workspace_name")
