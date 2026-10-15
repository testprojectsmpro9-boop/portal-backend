"""Add intake file attachments

Revision ID: 0020
Revises: 0019
Create Date: 2026-06-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "intake_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("intake_submission_id", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), nullable=True),
        sa.Column("file_type", postgresql.ENUM(name="filetype", create_type=False), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("stored_file_name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["intake_submission_id"], ["intake_submissions.id"]),
        sa.ForeignKeyConstraint(["uploaded_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_intake_files_id"), "intake_files", ["id"], unique=False)
    op.create_index(
        op.f("ix_intake_files_intake_submission_id"),
        "intake_files",
        ["intake_submission_id"],
        unique=False,
    )
    op.create_index(
        "ix_intake_files_uploaded_by_user_id",
        "intake_files",
        ["uploaded_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_intake_files_created_at",
        "intake_files",
        ["created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_intake_files_created_at", table_name="intake_files")
    op.drop_index("ix_intake_files_uploaded_by_user_id", table_name="intake_files")
    op.drop_index(op.f("ix_intake_files_intake_submission_id"), table_name="intake_files")
    op.drop_index(op.f("ix_intake_files_id"), table_name="intake_files")
    op.drop_table("intake_files")
