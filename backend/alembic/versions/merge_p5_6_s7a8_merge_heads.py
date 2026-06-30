"""merge Alembic heads: p5_6_drop_subject_column + s7a8b9c0d1e2

Revision ID: merge_p5_6_s7a8
Revises: p5_6_drop_subject_column, s7a8b9c0d1e2
Create Date: 2026-06-30

Pure merge migration — no DDL. Combines two independent branches
(questions.subject drop + import_batch_jobs.subject_id add) into
a single head so `alembic upgrade head` works in production.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "merge_p5_6_s7a8"
down_revision: Union[str, Sequence[str], None] = ("p5_6_drop_subject_column", "s7a8b9c0d1e2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
