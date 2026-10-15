"""Add structured offline intake fields

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-15

Adds nullable structured fields to intake_submissions so admin intake records
can be converted into ideas without packing every form answer into
raw_description. Existing records remain valid because every column is nullable.
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("intake_submissions", sa.Column("problem_statement", sa.Text(), nullable=True))
    op.add_column("intake_submissions", sa.Column("solution_description", sa.Text(), nullable=True))
    op.add_column("intake_submissions", sa.Column("category", sa.String(length=100), nullable=True))
    op.add_column("intake_submissions", sa.Column("sub_category", sa.String(length=255), nullable=True))
    op.add_column("intake_submissions", sa.Column("target_users", sa.Text(), nullable=True))
    op.add_column("intake_submissions", sa.Column("prototype_status", sa.String(length=100), nullable=True))
    op.add_column("intake_submissions", sa.Column("support_needed", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("intake_submissions", "support_needed")
    op.drop_column("intake_submissions", "prototype_status")
    op.drop_column("intake_submissions", "target_users")
    op.drop_column("intake_submissions", "sub_category")
    op.drop_column("intake_submissions", "category")
    op.drop_column("intake_submissions", "solution_description")
    op.drop_column("intake_submissions", "problem_statement")
