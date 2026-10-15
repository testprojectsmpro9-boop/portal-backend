"""Initial tables: users and ideas

Revision ID: 0001
Revises:
Create Date: 2026-05-08

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # --- Create enum types first (checkfirst=True = skip if already exists) ---
    sa.Enum(
        "SUPER_ADMIN", "TEAM_ADMIN_GLOBAL", "TEAM_ADMIN_LOCAL", "JURY", "INVENTOR",
        name="userrole",
    ).create(bind, checkfirst=True)

    sa.Enum(
        "NATIONAL_INTERNATIONAL", "LOCAL_REGIONAL", "K12",
        name="programtrack",
    ).create(bind, checkfirst=True)

    sa.Enum(
        "SUBMITTED", "UNDER_VERIFICATION", "NEEDS_MORE_INFORMATION",
        "PUBLIC_DOMAIN_REVIEW_PENDING", "PUBLIC_DOMAIN_CLEARED", "PUBLIC_DOMAIN_REJECTED",
        "FIELD_JURY_REVIEW_PENDING", "FIELD_JURY_REVIEW_IN_PROGRESS", "FIELD_REVIEW_CLEARED",
        "REJECTED_BY_JURY", "PROTOTYPE_REQUIRED", "PROTOTYPE_SUBMITTED",
        "MENTOR_ASSIGNED", "INCUBATION_RECOMMENDED", "SELECTED_FOR_LOCAL_SHOWCASE",
        "SELECTED_FOR_STATE_LEVEL", "RECOMMENDED_FOR_NATIONAL_LEVEL",
        "RECOMMENDED_FOR_INTERNATIONAL_LEVEL", "RECOGNITION_FUNDING_PATENT_SUPPORT",
        "CLOSED",
        name="ideastatus",
    ).create(bind, checkfirst=True)

    sa.Enum(
        "Agriculture", "Healthcare / Medical", "Education", "Environment", "Energy",
        "Water", "Waste Management", "Assistive Technology", "Women Safety",
        "Rural Development", "Electronics / IoT", "Mechanical Innovation",
        "AI / Software", "Social Innovation", "Others",
        name="ideacategory",
    ).create(bind, checkfirst=True)

    sa.Enum(
        "ONLINE_FORM", "OFFLINE_FORM", "LETTER_SCAN", "DOCUMENT", "AUDIO", "VIDEO",
        "PROTOTYPE_PHOTO", "DESIGN_SKETCH", "EMAIL_IMPORT", "WHATSAPP_IMPORT",
        "IN_PERSON", "OTHER",
        name="sourcetype",
    ).create(bind, checkfirst=True)

    # --- users table ---
    # create_type=False: enum type already exists above, don't create again
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum(name="userrole", create_type=False), nullable=False),
        sa.Column("program_track", sa.Enum(name="programtrack", create_type=False), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_index("ix_users_email", "users", ["email"])

    # --- ideas table ---
    op.create_table(
        "ideas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.String(20), nullable=False),
        sa.Column("inventor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("applicant_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("organization", sa.String(255), nullable=True),
        sa.Column("original_language", sa.String(50), nullable=True),
        sa.Column("program_track", sa.Enum(name="programtrack", create_type=False), nullable=False),
        sa.Column("source_type", sa.Enum(name="sourcetype", create_type=False), nullable=False),
        sa.Column("source_domain", sa.String(255), nullable=True),
        sa.Column("idea_title", sa.String(500), nullable=False),
        sa.Column("problem_statement", sa.Text(), nullable=True),
        sa.Column("solution_description", sa.Text(), nullable=True),
        sa.Column("category", sa.Enum(name="ideacategory", create_type=False), nullable=True),
        sa.Column("sub_category", sa.String(255), nullable=True),
        sa.Column("target_users", sa.Text(), nullable=True),
        sa.Column("prototype_status", sa.String(100), nullable=True),
        sa.Column("support_needed", sa.Text(), nullable=True),
        sa.Column("current_stage", sa.String(100), nullable=True),
        sa.Column("current_status", sa.Enum(name="ideastatus", create_type=False), nullable=False),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("admin_message", sa.Text(), nullable=True),
        sa.Column("is_public_tracking_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("application_id"),
    )
    op.create_index("ix_ideas_id", "ideas", ["id"])
    op.create_index("ix_ideas_application_id", "ideas", ["application_id"])
    op.create_index("ix_ideas_email", "ideas", ["email"])


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_ideas_email", table_name="ideas")
    op.drop_index("ix_ideas_application_id", table_name="ideas")
    op.drop_index("ix_ideas_id", table_name="ideas")
    op.drop_table("ideas")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")

    sa.Enum(name="sourcetype").drop(bind, checkfirst=True)
    sa.Enum(name="ideacategory").drop(bind, checkfirst=True)
    sa.Enum(name="ideastatus").drop(bind, checkfirst=True)
    sa.Enum(name="programtrack").drop(bind, checkfirst=True)
    sa.Enum(name="userrole").drop(bind, checkfirst=True)
