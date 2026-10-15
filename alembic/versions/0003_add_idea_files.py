"""Add idea_files table for file attachment metadata

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-09

WHAT WAS EXISTING:
  No file attachment support. Ideas had no linked files.

WHAT WE ADDED:
  idea_files table — stores metadata for every file uploaded to an idea.
  Files on disk live under uploads/ideas/{application_id}/{subfolder}/.
  file_path column stores the relative path (safe — no absolute server paths in DB).

WHY:
  Support document attachments, offline forms, letter scans, audio, video,
  prototype photos, and design sketches linked to idea submissions.

FIX NOTE (duplicate enum):
  sa.Enum(name=..., create_type=False) inside op.create_table is not fully
  honored by SQLAlchemy 2.x — it still emits a CREATE TYPE, causing
  "type already exists" when we also call .create() manually.
  Fix: use sqlalchemy.dialects.postgresql.ENUM which has explicit, reliable
  create_type semantics. We create the type once with checkfirst=True,
  then reference it in the table with create_type=False.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Define once — reused in upgrade() and downgrade()
_filetype_enum = postgresql.ENUM(
    "DOCUMENT", "OFFLINE_FORM", "LETTER_SCAN",
    "AUDIO", "VIDEO", "PROTOTYPE_PHOTO", "DESIGN_SKETCH", "OTHER",
    name="filetype",
)


def upgrade() -> None:
    bind = op.get_bind()

    # Step 1: create the PostgreSQL enum type explicitly.
    # checkfirst=True = skip safely if type already exists (idempotent).
    _filetype_enum.create(bind, checkfirst=True)

    # Step 2: create the table.
    # create_type=False on the column: enum type was already created above,
    # postgresql.ENUM with this flag will NOT emit another CREATE TYPE.
    op.create_table(
        "idea_files",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("idea_id", sa.Integer(), sa.ForeignKey("ideas.id"), nullable=False),
        sa.Column("uploaded_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "file_type",
            postgresql.ENUM(name="filetype", create_type=False),
            nullable=False,
        ),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("stored_file_name", sa.String(255), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_idea_files_id", "idea_files", ["id"])
    op.create_index("ix_idea_files_idea_id", "idea_files", ["idea_id"])


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_idea_files_idea_id", table_name="idea_files")
    op.drop_index("ix_idea_files_id", table_name="idea_files")
    op.drop_table("idea_files")

    # Drop the enum type after the table is gone
    _filetype_enum.drop(bind, checkfirst=True)
