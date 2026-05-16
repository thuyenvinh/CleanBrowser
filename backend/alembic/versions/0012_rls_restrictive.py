"""flip RLS policies from PERMISSIVE to RESTRICTIVE with system bypass

Phase 1 closure (task ZZ) — second half of the tenant isolation story
opened by migration ``0009_add_rls``. That migration created *permissive*
policies that fall through whenever ``app.current_tenant_id`` is unset, so
a router that forgets to set the GUC silently leaks data across tenants.
This migration switches the same nine tables to *restrictive* policies so
the default-deny behaviour is enforced at the database layer:

    * GUC unset / empty → ``USING`` evaluates to false → no rows visible.
    * GUC == ``__system__`` → ``USING`` evaluates to true → all rows
      visible. Used by background workers (``proxy_health``,
      ``automation_scheduler``), the test conftest truncate fixture, and
      ad-hoc maintenance scripts via :func:`backend.middleware_rls.system_context`.
    * GUC == ``<tenant uuid>`` → standard tenant filter, identical to the
      shape installed by 0009.

PostgreSQL combines policies with ``(any permissive true) AND (all
restrictive true)``. The wrinkle: a table with *only* restrictive
policies blocks every row, because there is no permissive policy that
returns true to satisfy the "any permissive" half. So this migration
keeps a single permissive ``tenant_isolation_allow`` policy that
unconditionally returns true and lets the actual filtering live in the
new ``tenant_isolation_restrict`` restrictive policy. The net effect is
identical to a single restrictive policy but works for INSERTs too
(which need ``WITH CHECK`` to pass under both halves).

The old ``tenant_isolation`` policy from 0009 is dropped first — leaving
it would re-introduce the open fall-through it expressed
(``GUC IS NULL OR ''`` → true → any-permissive wins → no filter).

This is also an Alembic merge: both ``0010_add_oauth_columns`` and
``0011_add_email_verification_tokens`` were authored off ``0009_add_rls``
in parallel, leaving two heads. Folding the merge into 0012 keeps the
linear history (and avoids a separate empty merge revision) without
modifying either 0010 or 0011.

AuditMiddleware status (deliberately out of scope for this task):
    ``backend.middleware_audit`` writes to ``audit_logs`` from a Starlette
    middleware that runs *after* the route handler. For authenticated
    requests the request-scoped tenant ContextVar is still populated when
    the middleware runs, so the GUC carries the tenant id and the
    restrictive policy lets the insert through. For requests that 401
    before authentication resolves, the policy's
    ``tenant_id IS NULL`` branch covers system-audit rows. If a real
    regression appears the middleware should be wrapped in
    ``system_context()`` — touching that file is outside the ZZ scope.

Revision ID: 0012_rls_restrictive
Revises: 0010_add_oauth_columns, 0011_add_email_verification_tokens
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0012_rls_restrictive"
# Merge the two parallel Phase 1 heads (0010 OAuth columns and 0011 email
# verification tokens) into a single linear history at 0012.
down_revision: Union[str, Sequence[str], None] = (
    "0010_add_oauth_columns",
    "0011_add_email_verification_tokens",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Sentinel GUC value that disables tenant filtering on a per-connection
# basis. Mirrors :data:`backend.middleware_rls.SYSTEM_TENANT_ID` — keep the
# two in sync. ``__system__`` was picked over the NIL UUID so a stray
# ``tenant_id::text`` comparison cannot accidentally match (no UUID column
# ever stores the sentinel string).
SYSTEM_GUC_VALUE = "__system__"


_DIRECT_TENANT_TABLES: tuple[str, ...] = ("workspaces", "users")
_VIA_WORKSPACE_TABLES: tuple[str, ...] = ("profiles", "proxies", "automations")

# Every table that gets a restrictive policy below also needs a no-op
# permissive policy so INSERTs can satisfy Postgres' "at least one
# permissive WITH CHECK passes" requirement. The list mirrors the table
# set touched by 0009.
_ALL_TABLES: tuple[str, ...] = (
    "workspaces",
    "users",
    "audit_logs",
    "profiles",
    "proxies",
    "automations",
    "automation_versions",
    "automation_runs",
    "automation_schedules",
)


def _create_allow_permissive(table: str) -> None:
    """Install a permissive ``tenant_isolation_allow`` policy that always
    returns true. Pairs with the restrictive policy created alongside —
    Postgres requires *some* permissive policy to grant access before the
    restrictive policies get a vote, so without this an INSERT (which
    evaluates ``WITH CHECK`` against both permissive and restrictive
    policies) would unconditionally fail with ``new row violates
    row-level security policy``."""
    op.execute(
        f"""
        CREATE POLICY tenant_isolation_allow ON {table}
        FOR ALL
        USING (true)
        WITH CHECK (true)
        """
    )


def _drop_allow_permissive(table: str) -> None:
    op.execute(
        f"DROP POLICY IF EXISTS tenant_isolation_allow ON {table}"
    )


def _drop_old(table: str) -> None:
    """Drop the permissive ``tenant_isolation`` policy from migration 0009."""
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")


def _drop_new(table: str) -> None:
    """Drop the restrictive policy created by this migration."""
    op.execute(
        f"DROP POLICY IF EXISTS tenant_isolation_restrict ON {table}"
    )


def _create_direct_restrictive(table: str) -> None:
    """Restrictive policy for tables with a direct ``tenant_id`` column.

    ``WITH CHECK`` mirrors ``USING`` so an INSERT/UPDATE that would land a
    row outside the caller's tenant is rejected with the same shape as a
    SELECT that would have hidden it — there is no asymmetric corner case
    where a row can be written but not read back.
    """
    op.execute(
        f"""
        CREATE POLICY tenant_isolation_restrict ON {table}
        AS RESTRICTIVE
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) = '{SYSTEM_GUC_VALUE}'
            OR tenant_id::text = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            current_setting('app.current_tenant_id', true) = '{SYSTEM_GUC_VALUE}'
            OR tenant_id::text = current_setting('app.current_tenant_id', true)
        )
        """
    )


def _create_via_workspace_restrictive(table: str) -> None:
    """Restrictive policy for tables reaching the tenant via ``workspace_id``.

    ``workspace_id IS NULL`` keeps the same legacy-orphan carve-out the
    permissive policy had so the migration is behaviour-preserving for
    properly-tenanted requests; the only thing that changes is that
    *missing* tenant context now denies instead of allowing. ``WITH
    CHECK`` mirrors ``USING`` for symmetry (see
    :func:`_create_direct_restrictive`).
    """
    op.execute(
        f"""
        CREATE POLICY tenant_isolation_restrict ON {table}
        AS RESTRICTIVE
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) = '{SYSTEM_GUC_VALUE}'
            OR workspace_id IS NULL
            OR EXISTS (
                SELECT 1 FROM workspaces w
                WHERE w.id = {table}.workspace_id
                  AND w.tenant_id::text
                      = current_setting('app.current_tenant_id', true)
            )
        )
        WITH CHECK (
            current_setting('app.current_tenant_id', true) = '{SYSTEM_GUC_VALUE}'
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


# ---------------------------------------------------------------------------
# Original permissive policy recreators — used only by downgrade(). Mirrors
# the body of migration 0009 verbatim so a downgrade restores the exact
# pre-0012 state. Keeping these inline (rather than importing 0009) avoids
# coupling the rollback to that module's filename / Python identifier.
# ---------------------------------------------------------------------------


def _recreate_direct_permissive(table: str) -> None:
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


def _recreate_via_workspace_permissive(table: str) -> None:
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
    # Install the no-op permissive policy on every RLS-enabled table first
    # so that no INSERT issued by the policy DDL below (none today, but
    # cheap insurance) can be blocked by the absence of a permissive vote.
    for tbl in _ALL_TABLES:
        _create_allow_permissive(tbl)

    # ---- direct tenant_id tables (workspaces, users) ----------------------
    for tbl in _DIRECT_TENANT_TABLES:
        _drop_old(tbl)
        _create_direct_restrictive(tbl)

    # ---- audit_logs: tenant_id may be NULL for system-emitted rows --------
    # Allowing tenant_id IS NULL keeps unauthenticated-failure audit inserts
    # (401 before user resolved) working without forcing the middleware to
    # opt into system_context for every request.
    _drop_old("audit_logs")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation_restrict ON audit_logs
        AS RESTRICTIVE
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) = '{SYSTEM_GUC_VALUE}'
            OR tenant_id IS NULL
            OR tenant_id::text = current_setting('app.current_tenant_id', true)
        )
        WITH CHECK (
            current_setting('app.current_tenant_id', true) = '{SYSTEM_GUC_VALUE}'
            OR tenant_id IS NULL
            OR tenant_id::text = current_setting('app.current_tenant_id', true)
        )
        """
    )

    # ---- workspace-scoped tables (profiles, proxies, automations) ---------
    for tbl in _VIA_WORKSPACE_TABLES:
        _drop_old(tbl)
        _create_via_workspace_restrictive(tbl)

    # ---- automation_versions: hops via automations -> workspaces ----------
    # ``USING`` and ``WITH CHECK`` are identical so an INSERT/UPDATE that
    # lands a child row pointing at a foreign automation is rejected with
    # the same predicate that hides it from a SELECT.
    _drop_old("automation_versions")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation_restrict ON automation_versions
        AS RESTRICTIVE
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) = '{SYSTEM_GUC_VALUE}'
            OR EXISTS (
                SELECT 1
                FROM automations a
                JOIN workspaces w ON w.id = a.workspace_id
                WHERE a.id = automation_versions.automation_id
                  AND w.tenant_id::text
                      = current_setting('app.current_tenant_id', true)
            )
        )
        WITH CHECK (
            current_setting('app.current_tenant_id', true) = '{SYSTEM_GUC_VALUE}'
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
    _drop_old("automation_runs")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation_restrict ON automation_runs
        AS RESTRICTIVE
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) = '{SYSTEM_GUC_VALUE}'
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
        WITH CHECK (
            current_setting('app.current_tenant_id', true) = '{SYSTEM_GUC_VALUE}'
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
    _drop_old("automation_schedules")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation_restrict ON automation_schedules
        AS RESTRICTIVE
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) = '{SYSTEM_GUC_VALUE}'
            OR EXISTS (
                SELECT 1
                FROM automations a
                JOIN workspaces w ON w.id = a.workspace_id
                WHERE a.id = automation_schedules.automation_id
                  AND w.tenant_id::text
                      = current_setting('app.current_tenant_id', true)
            )
        )
        WITH CHECK (
            current_setting('app.current_tenant_id', true) = '{SYSTEM_GUC_VALUE}'
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
    # Symmetric reversal: drop every restrictive policy created above, then
    # recreate the permissive equivalents from 0009 verbatim. The table list
    # and order mirror the upgrade so any future audit can diff the two
    # halves quickly.

    # ---- automation_schedules ----------------------------------------------
    _drop_new("automation_schedules")
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

    # ---- automation_runs ---------------------------------------------------
    _drop_new("automation_runs")
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

    # ---- automation_versions ----------------------------------------------
    _drop_new("automation_versions")
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

    # ---- via-workspace tables ---------------------------------------------
    for tbl in _VIA_WORKSPACE_TABLES:
        _drop_new(tbl)
        _recreate_via_workspace_permissive(tbl)

    # ---- audit_logs --------------------------------------------------------
    _drop_new("audit_logs")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON audit_logs
        FOR ALL
        USING (
            current_setting('app.current_tenant_id', true) IS NULL
            OR current_setting('app.current_tenant_id', true) = ''
            OR tenant_id::text = current_setting('app.current_tenant_id', true)
        )
        """
    )

    # ---- direct tenant_id tables (workspaces, users) ----------------------
    for tbl in _DIRECT_TENANT_TABLES:
        _drop_new(tbl)
        _recreate_direct_permissive(tbl)

    # ---- drop the no-op permissive vote installed by upgrade() -----------
    for tbl in _ALL_TABLES:
        _drop_allow_permissive(tbl)
