"""fix v8 columns that were never created on production

The v8_wrong_question_soft_delete migration was marked as applied via
a merge chain, but its upgrade() was never executed on production.
This migration adds the missing columns: mastered_at, is_active, removed_at.

Uses sa.inspect() to safely skip columns that already exist.

Revision ID: fix_v8_wrong_question_columns
Revises: v11_merge_heads
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa


revision = "fix_v8_wrong_question_columns"
down_revision = "v11_merge_heads"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = {c["name"] for c in insp.get_columns("wrong_questions")}

    additions = {
        "mastered_at": sa.Column("mastered_at", sa.DateTime(), nullable=True),
        "is_active": sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        "removed_at": sa.Column("removed_at", sa.DateTime(), nullable=True),
    }

    for col_name, col in additions.items():
        if col_name not in columns:
            op.add_column("wrong_questions", col)

    existing_idxs = {idx["name"] for idx in insp.get_indexes("wrong_questions")}

    if "ix_wq_user_active_next" not in existing_idxs:
        op.create_index(
            "ix_wq_user_active_next",
            "wrong_questions",
            ["user_id", "is_active"],
        )

    if "ix_wq_user_mastered" not in existing_idxs:
        op.create_index(
            "ix_wq_user_mastered",
            "wrong_questions",
            ["user_id", "mastered"],
        )

    if "ix_wq_user_review_count" not in existing_idxs:
        op.create_index(
            "ix_wq_user_review_count",
            "wrong_questions",
            ["user_id", "review_count"],
        )


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    columns = {c["name"] for c in insp.get_columns("wrong_questions")}
    existing_idxs = {idx["name"] for idx in insp.get_indexes("wrong_questions")}

    removals = ["mastered_at", "is_active", "removed_at"]
    for col_name in removals:
        if col_name in columns:
            op.drop_column("wrong_questions", col_name)

    for idx_name in ["ix_wq_user_active_next", "ix_wq_user_mastered", "ix_wq_user_review_count"]:
        if idx_name in existing_idxs:
            op.drop_index(idx_name, table_name="wrong_questions")
