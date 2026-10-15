"""Add jury_profiles, jury_assignments, evaluations tables

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-10

WHAT THIS MIGRATION DOES:
  Creates 2 new PostgreSQL enum types:
    reviewstatus   (PENDING, IN_PROGRESS, COMPLETED, REASSIGNED, CANCELLED)
    recommendation (SHORTLIST, REJECT, NEEDS_MORE_INFORMATION, PROTOTYPE_REQUIRED, NEEDS_IMPROVEMENT)

  Creates 3 new tables:
    jury_profiles    — expert profile for jury users
    jury_assignments — links jury users to ideas (1–3 per idea)
    evaluations      — jury evaluation records with 7 scoring criteria (max 100 total)
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_reviewstatus = postgresql.ENUM(
    "PENDING", "IN_PROGRESS", "COMPLETED", "REASSIGNED", "CANCELLED",
    name="reviewstatus",
)
_recommendation = postgresql.ENUM(
    "SHORTLIST", "REJECT", "NEEDS_MORE_INFORMATION", "PROTOTYPE_REQUIRED", "NEEDS_IMPROVEMENT",
    name="recommendation",
)


def upgrade():
    bind = op.get_bind()

    # Step 1 — create new enum types
    _reviewstatus.create(bind, checkfirst=True)
    _recommendation.create(bind, checkfirst=True)

    # Step 2 — jury_profiles
    op.create_table(
        "jury_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, index=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), unique=True, nullable=False, index=True),
        sa.Column("expertise_field", sa.String(255), nullable=True),
        sa.Column("sub_field", sa.String(255), nullable=True),
        sa.Column("qualification", sa.String(255), nullable=True),
        sa.Column("organization", sa.String(255), nullable=True),
        sa.Column("experience_years", sa.Integer(), nullable=True),
        sa.Column("max_review_capacity", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )

    # Step 3 — jury_assignments
    op.create_table(
        "jury_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, index=True, nullable=False),
        sa.Column("idea_id", sa.Integer(), sa.ForeignKey("ideas.id"), nullable=False, index=True),
        sa.Column("jury_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("assigned_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "review_status",
            postgresql.ENUM(name="reviewstatus", create_type=False),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("assigned_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("due_date", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )

    # Step 4 — evaluations
    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer(), primary_key=True, index=True, nullable=False),
        sa.Column("idea_id", sa.Integer(), sa.ForeignKey("ideas.id"), nullable=False, index=True),
        sa.Column("jury_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("problem_clarity_score", sa.Float(), nullable=False),
        sa.Column("novelty_score", sa.Float(), nullable=False),
        sa.Column("feasibility_score", sa.Float(), nullable=False),
        sa.Column("impact_score", sa.Float(), nullable=False),
        sa.Column("scalability_score", sa.Float(), nullable=False),
        sa.Column("prototype_readiness_score", sa.Float(), nullable=False),
        sa.Column("practical_usefulness_score", sa.Float(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column(
            "recommendation",
            postgresql.ENUM(name="recommendation", create_type=False),
            nullable=False,
        ),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )


def downgrade():
    op.drop_table("evaluations")
    op.drop_table("jury_assignments")
    op.drop_table("jury_profiles")
    bind = op.get_bind()
    _recommendation.drop(bind, checkfirst=True)
    _reviewstatus.drop(bind, checkfirst=True)
