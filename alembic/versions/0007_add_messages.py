"""Add messages table

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-10

WHAT THIS MIGRATION DOES:
  Creates the messages table for admin→inventor communication.
  Fields: id, idea_id, sender_user_id, receiver_user_id, message_type,
          message, is_internal, created_at.
  is_internal=False messages are visible to inventors.
  is_internal=True messages are admin-only internal notes.
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_messagetype_enum = postgresql.ENUM(
    "STATUS_UPDATE", "REQUEST_INFO", "RESPONSE", "GENERAL", "CONGRATULATIONS",
    name="messagetype",
)


def upgrade():
    bind = op.get_bind()
    _messagetype_enum.create(bind, checkfirst=True)

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True, index=True, nullable=False),
        sa.Column("idea_id", sa.Integer(), sa.ForeignKey("ideas.id"), nullable=False, index=True),
        sa.Column("sender_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("receiver_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "message_type",
            postgresql.ENUM(name="messagetype", create_type=False),
            nullable=False,
            server_default="GENERAL",
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_internal", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )


def downgrade():
    op.drop_table("messages")
    bind = op.get_bind()
    _messagetype_enum.drop(bind, checkfirst=True)
