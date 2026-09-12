"""add admin question review fields

Revision ID: h8c9d0e1f2g3
Revises: g7b8c9d0e1f2
Create Date: 2026-05-29 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "h8c9d0e1f2g3"
down_revision: Union[str, Sequence[str], None] = "g7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("question_imports") as batch_op:
        batch_op.add_column(sa.Column("reject_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))

    op.create_index(op.f("ix_questions_review_status_is_active"), "questions", ["review_status", "is_active"], unique=False)
    op.create_index(op.f("ix_questions_subject_review_status"), "questions", ["subject", "review_status"], unique=False)
    op.create_index(op.f("ix_questions_import_batch_id"), "questions", ["import_batch_id"], unique=False)
    op.create_index(op.f("ix_question_imports_question_id"), "question_imports", ["question_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_question_imports_question_id"), table_name="question_imports")
    op.drop_index(op.f("ix_questions_import_batch_id"), table_name="questions")
    op.drop_index(op.f("ix_questions_subject_review_status"), table_name="questions")
    op.drop_index(op.f("ix_questions_review_status_is_active"), table_name="questions")

    with op.batch_alter_table("question_imports") as batch_op:
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("reviewed_by")
        batch_op.drop_column("reject_reason")
