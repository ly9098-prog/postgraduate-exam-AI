"""add_performance_indexes

Revision ID: e5b62f3a4c7d
Revises: e4a51b2293da
Create Date: 2026-05-24 22:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b62f3a4c7d"
down_revision: Union[str, None] = "e4a51b2293da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEXES = [
    ("idx_practice_records_user_date", "practice_records", ["user_id", "answered_at"]),
    ("idx_practice_records_user_subject", "practice_records", ["user_id", "subject"]),
    ("idx_wrong_questions_user_mastered_date", "wrong_questions", ["user_id", "mastered", "next_review_date"]),
    ("idx_wrong_questions_user_question", "wrong_questions", ["user_id", "question_id"]),
    ("idx_review_schedules_user_next", "review_schedules", ["user_id", "next_review_at"]),
    ("idx_review_records_user_date", "review_records", ["user_id", "reviewed_at"]),
    ("idx_questions_subject_active", "questions", ["subject", "is_active"]),
    ("idx_answer_behavior_user_date", "answer_behaviors", ["user_id", "created_at"]),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    practice_columns = {column["name"] for column in inspector.get_columns("practice_records")}
    if "answered_at" not in practice_columns:
        with op.batch_alter_table("practice_records") as batch:
            batch.add_column(sa.Column("answered_at", sa.DateTime(), nullable=True))

    for index_name, table_name, columns in _INDEXES:
        existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        if index_name not in existing_indexes:
            op.create_index(index_name, table_name, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for index_name, table_name, _columns in reversed(_INDEXES):
        existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name=table_name)

    practice_columns = {column["name"] for column in inspector.get_columns("practice_records")}
    if "answered_at" in practice_columns:
        with op.batch_alter_table("practice_records") as batch:
            batch.drop_column("answered_at")
