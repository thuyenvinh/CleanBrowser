"""add browser_type to profiles

Phase 6 (task OOO) — dual-core engine support. Lets a user pick which
browser engine each profile launches: ``'chromium'`` (the default — uses
the CloakBrowser fingerprint-patched Chromium build) or ``'firefox'``
(stock Playwright Firefox; no CloakBrowser patches, so the fingerprint
score is lower but the detection signal *pattern* differs, which is
useful when a target site is profiling Chromium-specific tells).

Schema choices:

* ``browser_type`` is ``NOT NULL`` with a server default of ``'chromium'``
  so every pre-existing row gets the historical engine at migration time
  without an UPDATE pass. The check constraint locks the value to the
  exact two-element enum the dispatcher in ``browser_manager.launch``
  understands.
* A plain b-tree index is added on the column. The launch flow already
  reads the profile row by id (so it doesn't need the index), but the
  upcoming admin / worker-pool views will want "show me all Firefox
  profiles" filtering, and the column has only two distinct values —
  a partial index isn't worth the maintenance cost for that cardinality.

Revision ID: 0017_add_browser_type
Revises: 0016_add_invoices
Create Date: 2026-05-16
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0017_add_browser_type"
down_revision: Union[str, Sequence[str], None] = "0016_add_invoices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE profiles "
        "ADD COLUMN browser_type TEXT NOT NULL DEFAULT 'chromium'"
    )
    op.execute(
        "ALTER TABLE profiles ADD CONSTRAINT chk_browser_type "
        "CHECK (browser_type IN ('chromium', 'firefox'))"
    )
    op.execute(
        "CREATE INDEX ix_profiles_browser_type ON profiles(browser_type)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_profiles_browser_type")
    op.execute(
        "ALTER TABLE profiles DROP CONSTRAINT IF EXISTS chk_browser_type"
    )
    op.execute("ALTER TABLE profiles DROP COLUMN IF EXISTS browser_type")
