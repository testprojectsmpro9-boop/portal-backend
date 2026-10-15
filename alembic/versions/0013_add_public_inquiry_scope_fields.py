"""Add public inquiry scope fields

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("public_inquiries", sa.Column("program_track", sa.String(length=50), nullable=True))
    op.add_column("public_inquiries", sa.Column("visibility_scope", sa.String(length=50), nullable=True))
    op.add_column("public_inquiries", sa.Column("source_program", sa.String(length=50), nullable=True))
    op.add_column("public_inquiries", sa.Column("assigned_team_user_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_public_inquiries_assigned_team_user_id_users",
        "public_inquiries",
        "users",
        ["assigned_team_user_id"],
        ["id"],
    )
    op.create_index("ix_public_inquiries_program_track", "public_inquiries", ["program_track"])
    op.create_index("ix_public_inquiries_visibility_scope", "public_inquiries", ["visibility_scope"])
    op.create_index("ix_public_inquiries_source_program", "public_inquiries", ["source_program"])


def downgrade():
    op.drop_index("ix_public_inquiries_source_program", table_name="public_inquiries")
    op.drop_index("ix_public_inquiries_visibility_scope", table_name="public_inquiries")
    op.drop_index("ix_public_inquiries_program_track", table_name="public_inquiries")
    op.drop_constraint(
        "fk_public_inquiries_assigned_team_user_id_users",
        "public_inquiries",
        type_="foreignkey",
    )
    op.drop_column("public_inquiries", "assigned_team_user_id")
    op.drop_column("public_inquiries", "source_program")
    op.drop_column("public_inquiries", "visibility_scope")
    op.drop_column("public_inquiries", "program_track")
