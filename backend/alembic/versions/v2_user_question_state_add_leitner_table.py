"""add user_question_state table for Leitner box scheduling

V2: 新增用户题目复习状态表，支持 Leitner 盒子和 next_review_at 调度。

Revision ID: v2_user_question_state
Revises: v1_no_repeat_idx
Create Date: 2026-07-01
"""
import sqlalchemy as sa

from alembic import op

revision = "v2_user_question_state"
down_revision = "v1_no_repeat_idx"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())

    # 幂等检查：表是否已存在
    if "user_question_state" in insp.get_table_names():
        return

    op.create_table(
        "user_question_state",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("box_level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_answered_at", sa.DateTime(), nullable=True),
        sa.Column("next_review_at", sa.DateTime(), nullable=True),
        sa.Column("correct_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wrong_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("answer_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("wrong_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_is_correct", sa.Boolean(), nullable=True),
        sa.Column("last_answer_time_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "question_id", name="uq_user_question_state_user_question"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "idx_user_question_state_user_id",
        "user_question_state",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "idx_user_question_state_question_id",
        "user_question_state",
        ["question_id"],
        unique=False,
    )
    op.create_index(
        "idx_user_question_state_user_next_review",
        "user_question_state",
        ["user_id", "next_review_at"],
        unique=False,
    )
    op.create_index(
        "idx_user_question_state_user_question",
        "user_question_state",
        ["user_id", "question_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("idx_user_question_state_user_question", table_name="user_question_state")
    op.drop_index("idx_user_question_state_user_next_review", table_name="user_question_state")
    op.drop_index("idx_user_question_state_question_id", table_name="user_question_state")
    op.drop_index("idx_user_question_state_user_id", table_name="user_question_state")
    op.drop_table("user_question_state")
