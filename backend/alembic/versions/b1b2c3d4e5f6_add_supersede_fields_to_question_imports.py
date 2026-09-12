"""Add superseded_by_batch_id and superseded_at to question_imports

Revision ID: b1b2c3d4e5f6
Revises: 8cc0da3a47f1
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "8cc0da3a47f1"


def upgrade() -> None:
    op.add_column("question_imports", sa.Column("superseded_by_batch_id", sa.String(64), nullable=True))
    op.add_column("question_imports", sa.Column("superseded_at", sa.DateTime(), nullable=True))
    op.create_index(op.f("ix_question_imports_superseded_by_batch_id"), "question_imports", ["superseded_by_batch_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_question_imports_superseded_by_batch_id"), table_name="question_imports")
    op.drop_column("question_imports", "superseded_at")
    op.drop_column("question_imports", "superseded_by_batch_id")
