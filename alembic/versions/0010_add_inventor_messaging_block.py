"""Add inventor messaging block fields to ideas table

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-13

WHAT THIS MIGRATION DOES:
  Adds 4 columns to the `ideas` table to support admin-controlled
  per-idea inventor messaging block:
    - inventor_messages_blocked:            bool, default false
    - inventor_messages_blocked_reason:     text, nullable
    - inventor_messages_blocked_at:         datetime, nullable
    - inventor_messages_blocked_by_user_id: int FK → users.id, nullable
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ideas",
        sa.Column(
            "inventor_messages_blocked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "ideas",
        sa.Column("inventor_messages_blocked_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "ideas",
        sa.Column("inventor_messages_blocked_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "ideas",
        sa.Column(
            "inventor_messages_blocked_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("ideas", "inventor_messages_blocked_by_user_id")
    op.drop_column("ideas", "inventor_messages_blocked_at")
    op.drop_column("ideas", "inventor_messages_blocked_reason")
    op.drop_column("ideas", "inventor_messages_blocked")