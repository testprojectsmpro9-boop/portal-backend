"""Add file access logs

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-03
"""
from alembic import op
import sqlalchemy as sa


revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "file_access_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("idea_id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("user_email", sa.String(length=255), nullable=True),
        sa.Column("user_role", sa.String(length=50), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=100), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_file_access_logs_id"), "file_access_logs", ["id"])
    op.create_index(op.f("ix_file_access_logs_file_id"), "file_access_logs", ["file_id"])
    op.create_index(op.f("ix_file_access_logs_idea_id"), "file_access_logs", ["idea_id"])
    op.create_index(op.f("ix_file_access_logs_application_id"), "file_access_logs", ["application_id"])
    op.create_index(op.f("ix_file_access_logs_user_id"), "file_access_logs", ["user_id"])
    op.create_index(op.f("ix_file_access_logs_action"), "file_access_logs", ["action"])
    op.create_index(op.f("ix_file_access_logs_created_at"), "file_access_logs", ["created_at"])


def downgrade():
    op.drop_index(op.f("ix_file_access_logs_created_at"), table_name="file_access_logs")
    op.drop_index(op.f("ix_file_access_logs_action"), table_name="file_access_logs")
    op.drop_index(op.f("ix_file_access_logs_user_id"), table_name="file_access_logs")
    op.drop_index(op.f("ix_file_access_logs_application_id"), table_name="file_access_logs")
    op.drop_index(op.f("ix_file_access_logs_idea_id"), table_name="file_access_logs")
    op.drop_index(op.f("ix_file_access_logs_file_id"), table_name="file_access_logs")
    op.drop_index(op.f("ix_file_access_logs_id"), table_name="file_access_logs")
    op.drop_table("file_access_logs")
