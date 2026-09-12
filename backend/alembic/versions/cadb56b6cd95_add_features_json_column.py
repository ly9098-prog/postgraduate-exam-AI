"""Add features JSON column, migrate data from feature, keep old column for compat

Revision ID: cadb56b6cd95
Revises: 779303cf013b
Create Date: 2026-06-22
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "cadb56b6cd95"
down_revision: Union[str, Sequence[str], None] = "779303cf013b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add the new features JSON column
    op.add_column("admin_ai_model_configs", sa.Column("features", sa.JSON(), nullable=True))

    # Migrate existing data: feature="ocr" -> features='["ocr"]', feature=NULL -> features=NULL
    conn = op.get_bind()
    # Use string concat for portability; cast to json for PostgreSQL compat
    conn.exec_driver_sql(
        "UPDATE admin_ai_model_configs "
        "SET features = CASE "
        "  WHEN feature IS NOT NULL THEN CAST('[\"' || feature || '\"]' AS json) "
        "  ELSE NULL "
        "END"
    )


def downgrade() -> None:
    op.drop_column("admin_ai_model_configs", "features")
