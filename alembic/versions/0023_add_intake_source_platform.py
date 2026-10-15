"""add intake source platform

Revision ID: 0023
Revises: 0022_add_file_access_logs
Create Date: 2026-06-06
"""
from alembic import op
import sqlalchemy as sa


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("intake_submissions", sa.Column("source_platform", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("intake_submissions", "source_platform")
