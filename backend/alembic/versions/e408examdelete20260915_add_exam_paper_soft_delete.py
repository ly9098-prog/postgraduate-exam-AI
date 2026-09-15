"""add soft-delete timestamp for exam papers

Revision ID: e408examdelete20260915
Revises: e408examref20260913
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "e408examdelete20260915"
down_revision = "e408examref20260913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("exam_papers") as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_exam_papers_deleted_at", ["deleted_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("exam_papers") as batch_op:
        batch_op.drop_index("ix_exam_papers_deleted_at")
        batch_op.drop_column("deleted_at")
