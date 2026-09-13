"""add opaque public id for admin exam routes

Revision ID: e408examref20260913
Revises: d5f6a7b8c9d0
Create Date: 2026-09-13
"""

from __future__ import annotations

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision = "e408examref20260913"
down_revision = "d5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("exam_papers") as batch_op:
        batch_op.add_column(sa.Column("public_id", sa.String(length=32), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM exam_papers WHERE public_id IS NULL")).fetchall()
    for (paper_id,) in rows:
        bind.execute(
            sa.text("UPDATE exam_papers SET public_id = :public_id WHERE id = :paper_id"),
            {"public_id": uuid4().hex, "paper_id": int(paper_id)},
        )

    with op.batch_alter_table("exam_papers") as batch_op:
        batch_op.alter_column(
            "public_id",
            existing_type=sa.String(length=32),
            nullable=False,
        )
        batch_op.create_index("ix_exam_papers_public_id", ["public_id"], unique=True)


def downgrade() -> None:
    with op.batch_alter_table("exam_papers") as batch_op:
        batch_op.drop_index("ix_exam_papers_public_id")
        batch_op.drop_column("public_id")
