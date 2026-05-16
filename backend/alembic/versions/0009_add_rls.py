"""enable row-level security on tenant-scoped tables

Phase 1 (task PP) — wire up the Postgres-side half of the tenant isolation
story described in ``docs/ARCHITECTURE`` §2.2:

    Postgres + RLS: mỗi query tự động filter
    ``tenant_id = current_setting('app.tenant_id')`` — phòng leak data
    giữa tenant.

Application code already enforces this in ``dependencies.check_role_for_workspace``
and the workspace-scoped query helpers. This migration adds a *second*
fence at the database layer so a bug in a router (or a future code path
that forgets the membership check) cannot silently leak data across
tenants.

Design decisions:

* **Permissive policies, not restrictive.** Every policy unconditionally
  allows the row through when ``app.current_tenant_id`` is unset or empty.
  Tests, the legacy ``AUTH_TOKEN`` bearer flow, and one-off scripts thus
  keep working without any plumbing change — only requests that have
  travelled through :func:`backend.dependencies.get_optional_user` (which
  sets the ContextVar consumed by :func:`backend.database.get_db`) carry a
  tenant id and are therefore filtered. A future migration can flip these
  policies to ``RESTRICTIVE`` once every entry point is known to set the
  GUC. Doing it that way today would break the test suite and the legacy
  token flow at the same time, which is a poor tradeoff.

* **FORCE row level security.** The application connects as the table
  owner (``cleanbrowser`` in the standard compose), which by default
  bypasses its own RLS. ``ALTER TABLE … FORCE ROW LEVEL SECURITY`` removes
  that bypass so policies apply to the app user too. Superuser/migration
  roles still bypass — Alembic upgrades themselves are unaffected.

* **No denormalised ``tenant_id`` column on workspace-scoped tables.**
  ``profiles``, ``proxies``, ``automations``, ``automation_versions``,
  ``automation_runs`` and ``automation_schedules`` reach the tenant via
  their workspace (and, for the deeper tables, via a chain of FKs). The
  policy expresses that with a single ``EXISTS`` subquery against
  ``workspaces``. That trades one indexed PK lookup per row against the
  schema/backfill complexity of carrying ``tenant_id`` everywhere and was
  judged the right tradeoff for phase 1. Hot paths already filter by
  ``workspace_id`` themselves, so the EXISTS check usually short-circuits.

* **GUC name: ``app.current_tenant_id``** (not ``app.tenant_id`` as in the
  doc snippet) — picked to avoid colliding with any reserved
  ``app.*`` setting Postgres or extensions might introduce, and to read
  naturally next to ``app.current_user_id`` should that join the family
  later.

Tables touched (9):
    workspaces, users, profiles, proxies, automations,
    automation_versions, automation_runs, automation_schedules, audit_logs

Revision ID: 0009_add_rls
Revises: 0008_add_automations
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0009_add_rls"
down_revision: Union[str, Sequence[str], None] = "0008_add_automations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables that carry ``tenant_id`` as a direct column — the policy is a
# trivial scalar comparison.
_DIRECT_TENANT_TABLES: tuple[str, ...] = ("workspaces", "users", "audit_logs")

# Tables that reach the tenant via ``workspace_id → workspaces.tenant_id``.
_VIA_WORKSPACE_TABLES: tuple[str, ...] = ("profiles", "proxies", "automations")


def _enable_rls(table: str) -> None:
    """Enable + FORCE row-level security on a single table.

    Splitting these into two statements (and into a helper) makes the
    downgrade symmetric and keeps the per-table SQL readable.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def _disable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def _create_direct_policy(table: str) -> None:
    """Policy for tables with a direct ``tenant_id`` column.

    The ``current_setting(..., true)`` form returns NULL if the GUC is
    missing (rather than raising), which together with the explicit
    ``= ''`` check is what makes the policy permissive when no tenant has
    been pinned for the request.
    """
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) IS NULL
            OR current_setting('app.current_tenant_id', true) = ''
            OR tenant_id::text = current_setting('app.current_tenant_id', true)
        )
        """
    )


def _create_via_workspace_policy(table: str) -> None:
    """Policy for tables linked to the tenant through ``workspace_id``.

    ``workspace_id IS NULL`` is allowed unconditionally to keep legacy
    orphan profiles (see migration 0005) visible to the same code paths
    that handle them today; the app layer already special-cases NULL
    workspace ids and a sudden RLS-driven 404 would surprise callers.
    """
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) IS NULL
            OR current_setting('app.current_tenant_id', true) = ''
            OR workspace_id IS NULL
            OR EXISTS (
                SELECT 1 FROM workspaces w
                WHERE w.id = {table}.workspace_id
                  AND w.tenant_id::text
                      = current_setting('app.current_tenant_id', true)
            )
        )
        """
    )


def upgrade() -> None:
    # ---- direct tenant_id tables ------------------------------------------
    for tbl in _DIRECT_TENANT_TABLES:
        _enable_rls(tbl)
        _create_direct_policy(tbl)

    # ---- workspace-scoped tables ------------------------------------------
    for tbl in _VIA_WORKSPACE_TABLES:
        _enable_rls(tbl)
        _create_via_workspace_policy(tbl)

    # ---- automation_versions: hops via automations -> workspaces ----------
    _enable_rls("automation_versions")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON automation_versions
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) IS NULL
            OR current_setting('app.current_tenant_id', true) = ''
            OR EXISTS (
                SELECT 1
                FROM automations a
                JOIN workspaces w ON w.id = a.workspace_id
                WHERE a.id = automation_versions.automation_id
                  AND w.tenant_id::text
                      = current_setting('app.current_tenant_id', true)
            )
        )
        """
    )

    # ---- automation_runs: hops versions -> automations -> workspaces ------
    _enable_rls("automation_runs")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON automation_runs
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) IS NULL
            OR current_setting('app.current_tenant_id', true) = ''
            OR EXISTS (
                SELECT 1
                FROM automation_versions av
                JOIN automations a ON a.id = av.automation_id
                JOIN workspaces w ON w.id = a.workspace_id
                WHERE av.id = automation_runs.automation_version_id
                  AND w.tenant_id::text
                      = current_setting('app.current_tenant_id', true)
            )
        )
        """
    )

    # ---- automation_schedules: hops automations -> workspaces -------------
    _enable_rls("automation_schedules")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON automation_schedules
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) IS NULL
            OR current_setting('app.current_tenant_id', true) = ''
            OR EXISTS (
                SELECT 1
                FROM automations a
                JOIN workspaces w ON w.id = a.workspace_id
                WHERE a.id = automation_schedules.automation_id
                  AND w.tenant_id::text
                      = current_setting('app.current_tenant_id', true)
            )
        )
        """
    )


def downgrade() -> None:
    # Reverse order matters only insofar as policies must be dropped before
    # the table can be ``ALTER … DISABLE ROW LEVEL SECURITY``'d cleanly.
    for tbl in (
        "automation_schedules",
        "automation_runs",
        "automation_versions",
        *_VIA_WORKSPACE_TABLES,
        *_DIRECT_TENANT_TABLES,
    ):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {tbl}")
        _disable_rls(tbl)
