"""Add operational indexes

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-27
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_program_track", "users", ["program_track"])
    op.create_index("ix_users_is_active", "users", ["is_active"])
    op.create_index("ix_users_must_change_password", "users", ["must_change_password"])

    op.create_index("ix_ideas_current_status", "ideas", ["current_status"])
    op.create_index("ix_ideas_program_track", "ideas", ["program_track"])
    op.create_index("ix_ideas_visibility_scope", "ideas", ["visibility_scope"])
    op.create_index("ix_ideas_created_at", "ideas", ["created_at"])

    op.create_index("ix_jury_assignments_idea_jury_user", "jury_assignments", ["idea_id", "jury_user_id"])
    op.create_index("ix_evaluations_idea_jury_user", "evaluations", ["idea_id", "jury_user_id"])

    op.create_index("ix_idea_files_uploaded_by_user_id", "idea_files", ["uploaded_by_user_id"])
    op.create_index("ix_idea_files_created_at", "idea_files", ["created_at"])


def downgrade():
    op.drop_index("ix_idea_files_created_at", table_name="idea_files")
    op.drop_index("ix_idea_files_uploaded_by_user_id", table_name="idea_files")
    op.drop_index("ix_evaluations_idea_jury_user", table_name="evaluations")
    op.drop_index("ix_jury_assignments_idea_jury_user", table_name="jury_assignments")
    op.drop_index("ix_ideas_created_at", table_name="ideas")
    op.drop_index("ix_ideas_visibility_scope", table_name="ideas")
    op.drop_index("ix_ideas_program_track", table_name="ideas")
    op.drop_index("ix_ideas_current_status", table_name="ideas")
    op.drop_index("ix_users_must_change_password", table_name="users")
    op.drop_index("ix_users_is_active", table_name="users")
    op.drop_index("ix_users_program_track", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
