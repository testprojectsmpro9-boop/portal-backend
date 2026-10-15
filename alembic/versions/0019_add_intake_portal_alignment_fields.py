"""Add intake portal alignment fields

Revision ID: 0019
Revises: 0018
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


INTAKE_COLUMNS = (
    ("gender", sa.String(length=50)),
    ("team_name", sa.String(length=255)),
    ("team_member_count", sa.Integer()),
    ("team_member_names", sa.JSON()),
    ("guardian_name", sa.String(length=255)),
    ("guardian_phone", sa.String(length=20)),
    ("guardian_email", sa.String(length=255)),
    ("guardian_relationship", sa.String(length=100)),
    ("guardian_consent", sa.Boolean()),
    ("application_context", sa.Text()),
    ("uniqueness", sa.Text()),
    ("consent_data", sa.Boolean()),
    ("consent_original", sa.Boolean()),
    ("consent_contact", sa.Boolean()),
)

IDEA_COLUMNS = (
    ("guardian_name", sa.String(length=255)),
    ("guardian_phone", sa.String(length=20)),
    ("guardian_email", sa.String(length=255)),
    ("guardian_relationship", sa.String(length=100)),
    ("guardian_consent", sa.Boolean()),
    ("gender", sa.String(length=50)),
    ("application_context", sa.Text()),
    ("uniqueness", sa.Text()),
    ("consent_data", sa.Boolean()),
    ("consent_original", sa.Boolean()),
    ("consent_contact", sa.Boolean()),
)


def upgrade():
    for name, column_type in INTAKE_COLUMNS:
        op.add_column("intake_submissions", sa.Column(name, column_type, nullable=True))

    for name, column_type in IDEA_COLUMNS:
        op.add_column("ideas", sa.Column(name, column_type, nullable=True))


def downgrade():
    for name, _column_type in reversed(IDEA_COLUMNS):
        op.drop_column("ideas", name)

    for name, _column_type in reversed(INTAKE_COLUMNS):
        op.drop_column("intake_submissions", name)
