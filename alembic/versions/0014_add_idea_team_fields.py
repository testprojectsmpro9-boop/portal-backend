"""Add idea team submission fields

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("ideas", sa.Column("team_name", sa.String(length=255), nullable=True))
    op.add_column("ideas", sa.Column("team_member_count", sa.Integer(), nullable=True))
    op.add_column("ideas", sa.Column("team_member_names", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("ideas", "team_member_names")
    op.drop_column("ideas", "team_member_count")
    op.drop_column("ideas", "team_name")
