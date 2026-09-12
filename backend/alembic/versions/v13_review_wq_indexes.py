"""v13: add missing review_schedules(next_review_at) index and wrong_questions(created_at) index

Fixes:
1. review_schedules(user_id, next_review_at) WHERE mastered = false
   The v12 migration dropped idx_review_schedules_user_next (declared duplicate
   of ix_review_schedules_user_next_review which does not exist on production).
   This leaves the daily review query without an index on next_review_at.
2. wrong_questions(user_id, is_active, created_at DESC)
   Replaces ix_wq_user_active_next(user_id, is_active) with a three-column
   index that also covers ORDER BY created_at DESC for the wrong question list.

Revision ID: v13_review_wq_indexes
Revises: 2240ai_v12_missing_idx
Create Date: 2026-07-24
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "v13_review_wq_indexes"
down_revision: Union[str, Sequence[str], None] = "2240ai_v12_missing_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _idx_names(inspector, table: str) -> set[str]:
    return {idx["name"] for idx in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if dialect != "postgresql":
        return

    # ── 1. review_schedules(user_id, next_review_at) partial index ──
    # Critical for daily review query:
    #   SELECT ... FROM review_schedules
    #   WHERE user_id = ? AND mastered = false AND next_review_at <= NOW()
    #   ORDER BY next_review_at LIMIT 20
    rs_names = _idx_names(inspector, "review_schedules")
    idx_name = "ix_review_schedules_user_next_review"
    if idx_name not in rs_names:
        op.create_index(
            idx_name,
            "review_schedules",
            ["user_id", "next_review_at"],
            unique=False,
            postgresql_where=sa.text("mastered = false"),
        )

    # ── 2. wrong_questions(user_id, is_active, created_at DESC) ──
    # The wrong question list query sorts by created_at DESC.
    # Replace the old two-column index with a three-column one that
    # covers the ORDER BY.
    wq_names = _idx_names(inspector, "wrong_questions")
    old_idx = "ix_wq_user_active_next"
    new_idx = "ix_wq_user_active_created"

    if new_idx not in wq_names:
        if old_idx in wq_names:
            op.drop_index(old_idx, table_name="wrong_questions")
        op.create_index(
            new_idx,
            "wrong_questions",
            ["user_id", "is_active", sa.text("created_at DESC")],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name

    if dialect != "postgresql":
        return

    # ── 1. Drop review_schedules index ──
    rs_names = _idx_names(inspector, "review_schedules")
    idx_name = "ix_review_schedules_user_next_review"
    if idx_name in rs_names:
        op.drop_index(idx_name, table_name="review_schedules")

    # ── 2. Restore old wrong_questions index ──
    wq_names = _idx_names(inspector, "wrong_questions")
    new_idx = "ix_wq_user_active_created"
    old_idx = "ix_wq_user_active_next"

    if new_idx in wq_names:
        op.drop_index(new_idx, table_name="wrong_questions")
    if old_idx not in wq_names:
        op.create_index(
            old_idx,
            "wrong_questions",
            ["user_id", "is_active"],
            unique=False,
        )
