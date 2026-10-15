"""Repair idea_files: ensure filetype enum exists and file_type column is present

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-09

WHY THIS EXISTS:
  Migration 0003 created the idea_files table and filetype enum. On some local
  setups the migration ran partially (enum created, table created, but the
  file_type column ended up missing due to a partial rollback or manual DB edits).
  Developers who manually patched their local DB are already at a working state.
  This migration brings any broken or partial state into the correct final shape
  without touching users, ideas, or existing idea_files rows.

WHAT THIS DOES:
  1. Creates filetype PostgreSQL enum if it does not already exist.
  2. Adds file_type column to idea_files if it does not already exist.
  3. Uses server default 'DOCUMENT' so existing rows are not NULL.

SAFETY:
  - All steps are guarded with IF NOT EXISTS checks — fully idempotent.
  - No data is dropped.
  - No existing rows are deleted.
  - Safe to run on both clean and manually-patched DBs.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_filetype_enum = postgresql.ENUM(
    "DOCUMENT", "OFFLINE_FORM", "LETTER_SCAN",
    "AUDIO", "VIDEO", "PROTOTYPE_PHOTO", "DESIGN_SKETCH", "OTHER",
    name="filetype",
)


def upgrade() -> None:
    bind = op.get_bind()

    # Step 1: Ensure filetype enum type exists in PostgreSQL.
    # checkfirst=True = no-op if type already exists from migration 0003.
    _filetype_enum.create(bind, checkfirst=True)

    # Step 2: Add file_type column only if missing.
    # Raw SQL DO block = idempotent; safe on both partial and clean states.
    # Server default 'DOCUMENT' covers any existing rows without file_type.
    bind.execute(sa.text("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'idea_files'
                  AND column_name = 'file_type'
            ) THEN
                ALTER TABLE idea_files
                    ADD COLUMN file_type filetype NOT NULL DEFAULT 'DOCUMENT';
            END IF;
        END $$;
    """))


def downgrade() -> None:
    bind = op.get_bind()

    # Drop file_type column only if it exists.
    # Do NOT drop filetype enum here — it belongs to migration 0003.
    bind.execute(sa.text("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'idea_files'
                  AND column_name = 'file_type'
            ) THEN
                ALTER TABLE idea_files DROP COLUMN file_type;
            END IF;
        END $$;
    """))
