"""Add public inquiries table

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_publicinquirytype = postgresql.ENUM(
    "CONTACT",
    "COLLABORATION",
    "MEMBERSHIP",
    "REGISTER_INTEREST",
    "SCHOOL_PARTNERSHIP",
    "OTHER",
    name="publicinquirytype",
)


def upgrade():
    bind = op.get_bind()
    _publicinquirytype.create(bind, checkfirst=True)

    op.create_table(
        "public_inquiries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "inquiry_type",
            postgresql.ENUM(name="publicinquirytype", create_type=False),
            nullable=False,
        ),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("organization", sa.String(length=255), nullable=True),
        sa.Column("interest_area", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="NEW"),
        sa.Column("source_page", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_public_inquiries_id", "public_inquiries", ["id"])
    op.create_index("ix_public_inquiries_inquiry_type", "public_inquiries", ["inquiry_type"])
    op.create_index("ix_public_inquiries_email", "public_inquiries", ["email"])
    op.create_index("ix_public_inquiries_status", "public_inquiries", ["status"])


def downgrade():
    bind = op.get_bind()

    op.drop_index("ix_public_inquiries_status", table_name="public_inquiries")
    op.drop_index("ix_public_inquiries_email", table_name="public_inquiries")
    op.drop_index("ix_public_inquiries_inquiry_type", table_name="public_inquiries")
    op.drop_index("ix_public_inquiries_id", table_name="public_inquiries")
    op.drop_table("public_inquiries")

    _publicinquirytype.drop(bind, checkfirst=True)
