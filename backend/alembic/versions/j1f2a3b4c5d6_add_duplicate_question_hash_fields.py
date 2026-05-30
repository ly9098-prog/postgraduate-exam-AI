"""add duplicate question hash fields

Revision ID: j1f2a3b4c5d6
Revises: i0e1f2a3b4c5
Create Date: 2026-05-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "i0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {item["name"] for item in inspector.get_columns(table_name)}
    if column.name not in existing_columns:
        with op.batch_alter_table(table_name) as batch:
            batch.add_column(column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {item["name"] for item in inspector.get_indexes(table_name)}
    if index_name not in existing_indexes:
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    _add_column_if_missing("questions", sa.Column("question_hash", sa.String(length=32), nullable=True))
    _add_column_if_missing("question_imports", sa.Column("question_hash", sa.String(length=32), nullable=True))
    _add_column_if_missing("question_imports", sa.Column("duplicate_status", sa.String(length=32), nullable=False, server_default="normal"))
    _add_column_if_missing("question_imports", sa.Column("duplicate_of_question_id", sa.BigInteger(), nullable=True))
    _add_column_if_missing("question_imports", sa.Column("duplicate_of_import_id", sa.BigInteger(), nullable=True))

    _create_index_if_missing("ix_questions_question_hash", "questions", ["question_hash"])
    _create_index_if_missing("ix_question_imports_question_hash", "question_imports", ["question_hash"])
    _create_index_if_missing("ix_question_imports_duplicate_status", "question_imports", ["duplicate_status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for index_name, table_name in [
        ("ix_question_imports_duplicate_status", "question_imports"),
        ("ix_question_imports_question_hash", "question_imports"),
        ("ix_questions_question_hash", "questions"),
    ]:
        existing_indexes = {item["name"] for item in inspector.get_indexes(table_name)}
        if index_name in existing_indexes:
            op.drop_index(index_name, table_name=table_name)

    for table_name, column_name in [
        ("question_imports", "duplicate_of_import_id"),
        ("question_imports", "duplicate_of_question_id"),
        ("question_imports", "duplicate_status"),
        ("question_imports", "question_hash"),
        ("questions", "question_hash"),
    ]:
        existing_columns = {item["name"] for item in inspector.get_columns(table_name)}
        if column_name in existing_columns:
            with op.batch_alter_table(table_name) as batch:
                batch.drop_column(column_name)
