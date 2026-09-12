"""add deleted_at column to users table for soft delete

Revision ID: 6f7d91a01d3b
Revises: t5g6h7i8j9k0
Create Date: 2026-07-11 00:51:34.079638

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "6f7d91a01d3b"
down_revision: Union[str, Sequence[str], None] = "t5g6h7i8j9k0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = {c["name"] for c in insp.get_columns("users")}
    if "deleted_at" not in columns:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("deleted_at")
