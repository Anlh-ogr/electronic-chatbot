"""Fix chats.chat_id compatibility with legacy chats.id schema.

Revision ID: 20260501_01
Revises:
Create Date: 2026-05-01 11:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260501_01"
down_revision = None
branch_labels = None
depends_on = None


def _has_column(bind: sa.engine.Connection, table_name: str, column_name: str) -> bool:
    result = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
            """
        ),
        {"table_name": table_name, "column_name": column_name},
    ).first()
    return result is not None


def upgrade() -> None:
    bind = op.get_bind()

    has_chat_id = _has_column(bind, "chats", "chat_id")
    has_id = _has_column(bind, "chats", "id")

    if not has_chat_id and has_id:
        op.add_column("chats", sa.Column("chat_id", sa.String(length=36), nullable=True))
        op.execute("UPDATE chats SET chat_id = CAST(id AS varchar(36)) WHERE chat_id IS NULL")

    if _has_column(bind, "chats", "chat_id"):
        op.create_index("ix_chats_chat_id", "chats", ["chat_id"], unique=True, if_not_exists=True)
        op.alter_column("chats", "chat_id", existing_type=sa.String(length=36), nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind, "chats", "chat_id"):
        op.drop_index("ix_chats_chat_id", table_name="chats", if_exists=True)
        op.drop_column("chats", "chat_id")
