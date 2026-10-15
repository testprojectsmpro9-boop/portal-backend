"""Add VIEW_ADMIN_LOCAL, VIEW_ADMIN_GLOBAL, VIEW_ADMIN_BOTH to userrole enum

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-07

WHY:
  New read-only admin roles for stakeholders who need visibility into ideas
  and jury evaluations (scoped local/global/both, matching the existing
  TEAM_ADMIN_LOCAL / TEAM_ADMIN_GLOBAL scope rules) without any ability to
  create, edit, delete, or otherwise mutate records.

WHAT THIS DOES:
  Adds 3 new labels to the existing PostgreSQL `userrole` enum type via
  ALTER TYPE ... ADD VALUE. Does not touch any existing role, table, or
  column. No existing user rows are affected.

NOTE:
  PostgreSQL enum values cannot be removed by ALTER TYPE. A true downgrade
  would require rebuilding the enum type (create new type, migrate column,
  drop old type) and is deliberately not attempted here to avoid risking
  data loss on a production role column. downgrade() is a documented no-op.

NOTE:
  ALTER TYPE ... ADD VALUE cannot be called from within the same
  transaction that later reads/uses the new value (a PostgreSQL restriction
  on enums added mid-transaction). This migration only adds the values; no
  other statement in this migration references them, so it is safe to run
  as a normal transactional migration on PostgreSQL 12+.
"""
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

_NEW_VALUES = ("VIEW_ADMIN_LOCAL", "VIEW_ADMIN_GLOBAL", "VIEW_ADMIN_BOTH")


def upgrade():
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE userrole ADD VALUE IF NOT EXISTS '{value}'")


def downgrade():
    # PostgreSQL does not support removing enum values without rebuilding
    # the type. Intentionally left as a no-op — see module docstring.
    pass
