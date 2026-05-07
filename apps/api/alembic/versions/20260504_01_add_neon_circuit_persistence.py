"""Add Neon circuit persistence tables and columns.

Revision ID: 20260504_01
Revises: 20260501_01
Create Date: 2026-05-04 19:40:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260504_01"
down_revision = "20260501_01"
branch_labels = None
depends_on = None


def _has_table(bind: sa.engine.Connection, table_name: str) -> bool:
    result = bind.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    ).first()
    return result is not None


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

    if _has_table(bind, "circuits"):
        if not _has_column(bind, "circuits", "topology_family"):
            op.add_column("circuits", sa.Column("topology_family", sa.String(length=50), nullable=True))
        if not _has_column(bind, "circuits", "topology_variant"):
            op.add_column("circuits", sa.Column("topology_variant", sa.String(length=100), nullable=True))
        if not _has_column(bind, "circuits", "circuit_ir"):
            op.add_column("circuits", sa.Column("circuit_ir", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        if not _has_column(bind, "circuits", "user_session"):
            op.add_column("circuits", sa.Column("user_session", sa.String(length=255), nullable=True))

    if not _has_table(bind, "circuit_exports"):
        op.create_table(
            "circuit_exports",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("circuit_id", sa.UUID(), sa.ForeignKey("circuits.circuit_id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("export_type", sa.String(length=20), nullable=False),
            sa.Column("file_path", sa.String(length=500), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
        )

    if not _has_table(bind, "simulation_results"):
        op.create_table(
            "simulation_results",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("circuit_id", sa.UUID(), sa.ForeignKey("circuits.circuit_id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("sim_type", sa.String(length=20), nullable=False),
            sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _has_table(bind, "simulation_results"):
        op.drop_table("simulation_results")

    if _has_table(bind, "circuit_exports"):
        op.drop_table("circuit_exports")

    if _has_table(bind, "circuits"):
        if _has_column(bind, "circuits", "user_session"):
            op.drop_column("circuits", "user_session")
        if _has_column(bind, "circuits", "circuit_ir"):
            op.drop_column("circuits", "circuit_ir")
        if _has_column(bind, "circuits", "topology_variant"):
            op.drop_column("circuits", "topology_variant")
        if _has_column(bind, "circuits", "topology_family"):
            op.drop_column("circuits", "topology_family")
