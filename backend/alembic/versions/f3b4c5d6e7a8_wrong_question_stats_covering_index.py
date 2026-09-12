"""add covering index for wrong-question statistics

The wrong-question dashboard filters active rows by user and computes mastered /
unmastered / high-frequency counts.  Production logs showed the unmastered count
falling back to a costly scan because the existing indexes do not cover the full
predicate and ``review_count`` used by the high-frequency aggregate.

Revision ID: f3b4c5d6e7a8
Revises: e0f1a2b3c4d5
Create Date: 2026-09-04
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "f3b4c5d6e7a8"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None

INDEX_NAME = "ix_wrong_questions_user_active_mastered_review"
INDEX_COLUMNS = ("user_id", "is_active", "mastered", "review_count")


def _index_names(inspector: sa.Inspector) -> set[str]:
    return {
        idx.get("name")
        for idx in inspector.get_indexes("wrong_questions")
        if idx.get("name")
    }


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "wrong_questions" not in inspector.get_table_names():
        raise RuntimeError(
            "wrong_questions table is missing; apply earlier Alembic revisions first"
        )

    columns = {column["name"] for column in inspector.get_columns("wrong_questions")}
    missing = [name for name in INDEX_COLUMNS if name not in columns]
    if missing:
        raise RuntimeError(
            "wrong_questions is missing columns required by the stats index: "
            + ", ".join(missing)
        )

    if INDEX_NAME not in _index_names(inspector):
        op.create_index(
            INDEX_NAME,
            "wrong_questions",
            list(INDEX_COLUMNS),
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "wrong_questions" not in inspector.get_table_names():
        return

    if INDEX_NAME in _index_names(inspector):
        op.drop_index(INDEX_NAME, table_name="wrong_questions")
