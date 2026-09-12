"""add practice_records columns for refactored model

Revision ID: u9v8w7x6y5z4
Revises: t4c5d6e7f8g9
Create Date: 2026-06-28 23:55:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "u9v8w7x6y5z4"
down_revision: Union[str, Sequence[str], None] = "t4c5d6e7f8g9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns(table)]
    return column in cols


def upgrade() -> None:
    if not _has_column("practice_records", "question_id"):
        op.add_column("practice_records", sa.Column("question_id", sa.Integer(), nullable=True))
    if not _has_column("practice_records", "question_type"):
        op.add_column("practice_records", sa.Column("question_type", sa.String(32), nullable=False, server_default="choice"))
    if not _has_column("practice_records", "user_answer"):
        op.add_column("practice_records", sa.Column("user_answer", sa.Text(), nullable=False, server_default=""))
    if not _has_column("practice_records", "is_correct"):
        op.add_column("practice_records", sa.Column("is_correct", sa.Boolean(), nullable=False, server_default="0"))
    if not _has_column("practice_records", "used_time"):
        op.add_column("practice_records", sa.Column("used_time", sa.Integer(), nullable=True))


def downgrade() -> None:
    for col in ("used_time", "is_correct", "user_answer", "question_type", "question_id"):
        if _has_column("practice_records", col):
            op.drop_column("practice_records", col)
