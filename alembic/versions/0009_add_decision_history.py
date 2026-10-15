"""Add idea_decisions and status_history tables

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-10

WHAT THIS MIGRATION DOES:
  1. Creates `admindecision` PostgreSQL enum (13 values).
  2. Creates `idea_decisions` table — formal decision records with old/new status snapshots.
  3. Creates `status_history` table — append-only log of every status/stage change.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_admindecision_enum = postgresql.ENUM(
    "SHORTLISTED",
    "REJECTED",
    "NEEDS_MORE_INFORMATION",
    "PROTOTYPE_REQUIRED",
    "PROTOTYPE_APPROVED",
    "MENTORSHIP_ASSIGNED",
    "INCUBATION_RECOMMENDED",
    "SELECTED_FOR_LOCAL_SHOWCASE",
    "SELECTED_FOR_STATE_LEVEL",
    "RECOMMENDED_FOR_NATIONAL_LEVEL",
    "RECOMMENDED_FOR_INTERNATIONAL_LEVEL",
    "RECOGNITION_FUNDING_PATENT_SUPPORT",
    "CLOSED",
    name="admindecision",
)


def upgrade():
    bind = op.get_bind()
    _admindecision_enum.create(bind, checkfirst=True)

    op.create_table(
        "idea_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, index=True, nullable=False),
        sa.Column("idea_id", sa.Integer(), sa.ForeignKey("ideas.id"), nullable=False, index=True),
        sa.Column("decided_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "decision",
            postgresql.ENUM(name="admindecision", create_type=False),
            nullable=False,
        ),
        sa.Column("old_status", sa.String(100), nullable=True),
        sa.Column("old_pathway_stage", sa.String(100), nullable=True),
        sa.Column("new_status", sa.String(100), nullable=True),
        sa.Column("new_pathway_stage", sa.String(100), nullable=True),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column("public_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )

    op.create_table(
        "status_history",
        sa.Column("id", sa.Integer(), primary_key=True, index=True, nullable=False),
        sa.Column("idea_id", sa.Integer(), sa.ForeignKey("ideas.id"), nullable=False, index=True),
        sa.Column("changed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("old_status", sa.String(100), nullable=True),
        sa.Column("new_status", sa.String(100), nullable=True),
        sa.Column("old_stage", sa.String(100), nullable=True),
        sa.Column("new_stage", sa.String(100), nullable=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )


def downgrade():
    op.drop_table("status_history")
    op.drop_table("idea_decisions")
    bind = op.get_bind()
    _admindecision_enum.drop(bind, checkfirst=True)
