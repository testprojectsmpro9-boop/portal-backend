"""Add intake_submissions table and extend pathwaystage enum

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-09

WHAT WAS EXISTING:
  Ideas table handled all submissions including offline/non-standard ones.
  No staging area for admin intake processing workflow.

WHAT WE ADDED:
  1. ADMIN_VERIFICATION added to pathwaystage enum — used when an intake is
     converted to a formal idea, marking it as "just arrived from intake desk".
  2. intakestatus enum — 7-state workflow for intake processing.
  3. completenessstatus enum — 3-value completeness check flag.
  4. intake_submissions table — staging table for offline/non-standard submissions.

WHY:
  Admin team receives ideas via offline forms, letter scans, WhatsApp, in-person
  meetings, etc. These need a staging area where admin can standardize the data
  before it enters the formal review pipeline.

REUSED ENUMS (create_type=False — already exist from earlier migrations):
  sourcetype (0001), sourceprogram (0002), applicanttype (0002), visibilityscope (0002)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_intakestatus_enum = postgresql.ENUM(
    "RAW_RECEIVED", "STANDARDIZATION_PENDING", "STANDARDIZED",
    "NEEDS_MORE_INFORMATION", "READY_FOR_REVIEW", "CONVERTED_TO_IDEA", "CLOSED",
    name="intakestatus",
)

_completenessstatus_enum = postgresql.ENUM(
    "NOT_CHECKED", "COMPLETE", "INCOMPLETE",
    name="completenessstatus",
)


def upgrade() -> None:
    bind = op.get_bind()

    # Step 1: Add ADMIN_VERIFICATION to existing pathwaystage enum.
    # Use DO block with pg_enum check — fully idempotent, safe in transactions.
    bind.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum e
                JOIN pg_type t ON e.enumtypid = t.oid
                WHERE t.typname = 'pathwaystage' AND e.enumlabel = 'ADMIN_VERIFICATION'
            ) THEN
                ALTER TYPE pathwaystage ADD VALUE 'ADMIN_VERIFICATION';
            END IF;
        END $$;
    """))

    # Step 2: Create new enum types
    _intakestatus_enum.create(bind, checkfirst=True)
    _completenessstatus_enum.create(bind, checkfirst=True)

    # Step 3: Create intake_submissions table
    # Reused enums (sourcetype, sourceprogram, applicanttype, visibilityscope)
    # use create_type=False — already exist from migrations 0001/0002.
    op.create_table(
        "intake_submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("intake_id", sa.String(20), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("assigned_team_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "source_type",
            postgresql.ENUM(name="sourcetype", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "source_program",
            postgresql.ENUM(name="sourceprogram", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "applicant_type",
            postgresql.ENUM(name="applicanttype", create_type=False),
            nullable=True,
        ),
        sa.Column(
            "visibility_scope",
            postgresql.ENUM(name="visibilityscope", create_type=False),
            nullable=True,
        ),
        sa.Column("original_language", sa.String(50), nullable=True),
        sa.Column("applicant_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("organization", sa.String(255), nullable=True),
        sa.Column("raw_title", sa.String(500), nullable=False),
        sa.Column("raw_description", sa.Text(), nullable=True),
        sa.Column("standardized_idea_id", sa.Integer(), sa.ForeignKey("ideas.id"), nullable=True),
        sa.Column(
            "intake_status",
            postgresql.ENUM(name="intakestatus", create_type=False),
            nullable=False,
            server_default="RAW_RECEIVED",
        ),
        sa.Column(
            "completeness_status",
            postgresql.ENUM(name="completenessstatus", create_type=False),
            nullable=False,
            server_default="NOT_CHECKED",
        ),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("missing_information_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("intake_id"),
    )
    op.create_index("ix_intake_submissions_id", "intake_submissions", ["id"])
    op.create_index("ix_intake_submissions_intake_id", "intake_submissions", ["intake_id"])
    op.create_index("ix_intake_submissions_created_by", "intake_submissions", ["created_by_user_id"])
    op.create_index("ix_intake_submissions_source_program", "intake_submissions", ["source_program"])
    op.create_index("ix_intake_submissions_intake_status", "intake_submissions", ["intake_status"])


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_intake_submissions_intake_status", table_name="intake_submissions")
    op.drop_index("ix_intake_submissions_source_program", table_name="intake_submissions")
    op.drop_index("ix_intake_submissions_created_by", table_name="intake_submissions")
    op.drop_index("ix_intake_submissions_intake_id", table_name="intake_submissions")
    op.drop_index("ix_intake_submissions_id", table_name="intake_submissions")
    op.drop_table("intake_submissions")

    _completenessstatus_enum.drop(bind, checkfirst=True)
    _intakestatus_enum.drop(bind, checkfirst=True)

    # NOTE: we do NOT remove ADMIN_VERIFICATION from pathwaystage here.
    # ALTER TYPE REMOVE VALUE is not supported in PostgreSQL.
    # The value is harmless; existing ideas using it would break if removed.
