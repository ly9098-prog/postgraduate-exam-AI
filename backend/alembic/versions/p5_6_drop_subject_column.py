"""Drop questions.subject column — subject_id is now the only identifier.

Revision ID: p5_6_drop_subject_column
Revises: p5_5_1_fix_subjects
Create Date: 2026-06-29

Prerequisites:
- All questions.subject values have been backfilled to questions.subject_id
  via scripts/backfill_subject_id.py

Removes the legacy string subject column from the questions table.
The subject_id FK (→ subjects.id) is now the single source of truth.
"""

from alembic import op
import sqlalchemy as sa


revision = "p5_6_drop_subject_column"
down_revision = "p5_5_1_fix_subjects"
branch_labels = None
depends_on = None


def _has_column(inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_table(inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _drop_index_if_exists(inspector, table: str, index: str) -> None:
    existing = {idx["name"] for idx in inspector.get_indexes(table)}
    if index in existing:
        op.drop_index(index, table_name=table)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop ALL indexes referencing subject column BEFORE dropping the column
    for idx in ["ix_questions_subject", "ix_questions_subject_review_status", "idx_questions_subject_active"]:
        _drop_index_if_exists(inspector, "questions", idx)

    # Drop subject from questions
    if _has_column(inspector, "questions", "subject"):
        op.drop_column("questions", "subject")

    # Drop subject from question_imports (also legacy, all refs migrated)
    _drop_index_if_exists(inspector, "question_imports", "ix_question_imports_subject")
    if _has_column(inspector, "question_imports", "subject"):
        op.drop_column("question_imports", "subject")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Re-add subject columns as nullable strings
    if _has_table(inspector, "questions") and not _has_column(inspector, "questions", "subject"):
        op.add_column("questions", sa.Column("subject", sa.String(32), nullable=True))

    if _has_table(inspector, "question_imports") and not _has_column(inspector, "question_imports", "subject"):
        op.add_column("question_imports", sa.Column("subject", sa.String(32), nullable=True))
