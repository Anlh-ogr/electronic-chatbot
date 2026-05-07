"""alter circuit_id to uuid in industrial_routing_jobs

Revision ID: b1c4f61839e8
Revises: 20260504_01
Create Date: 2026-05-05 01:09:16.080752
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1c4f61839e8'
down_revision = '20260504_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # varchar to uuid
    op.alter_column(
        "industrial_routing_jobs",
        "circuit_id",
        type_=sa.UUID(),
        postgresql_using="circuit_id::uuid",
        existing_type=sa.VARCHAR(length=36),
    )


def downgrade() -> None:
    # uuid to varchar
    op.alter_column(
        "industrial_routing_jobs",
        "circuit_id",
        type_=sa.VARCHAR(length=36),
        existing_type=sa.UUID(as_uuid=True),
    )
