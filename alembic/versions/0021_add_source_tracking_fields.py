"""Add source tracking fields to ideas table

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-02

Adds three nullable columns for origin-platform tracking.
source_domain already existed since migration 0001.
"""
from alembic import op
import sqlalchemy as sa


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ideas", sa.Column("source_platform", sa.String(50), nullable=True))
    op.add_column("ideas", sa.Column("source_url", sa.String(2000), nullable=True))
    op.add_column("ideas", sa.Column("referrer_url", sa.String(2000), nullable=True))


def downgrade():
    op.drop_column("ideas", "referrer_url")
    op.drop_column("ideas", "source_url")
    op.drop_column("ideas", "source_platform")
