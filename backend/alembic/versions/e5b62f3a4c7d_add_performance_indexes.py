"""add_performance_indexes

Revision ID: e5b62f3a4c7d
Revises: e4a51b2293da
Create Date: 2026-05-24 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5b62f3a4c7d"
down_revision: Union[str, None] = "e4a51b2293da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 刷题记录：用户+时间复合索引
    op.create_index(
        "idx_practice_records_user_date",
        "practice_records",
        ["user_id", "answered_at"],
    )
    # 刷题记录：用户+科目
    op.create_index(
        "idx_practice_records_user_subject",
        "practice_records",
        ["user_id", "subject"],
    )
    # 错题：用户+掌握状态+复习日期
    op.create_index(
        "idx_wrong_questions_user_mastered_date",
        "wrong_questions",
        ["user_id", "mastered", "next_review_date"],
    )
    # 错题：用户+科目（join 查询优化）
    op.create_index(
        "idx_wrong_questions_user_question",
        "wrong_questions",
        ["user_id", "question_id"],
    )
    # 复习调度：用户+下次复习时间
    op.create_index(
        "idx_review_schedules_user_next",
        "review_schedules",
        ["user_id", "next_review_at"],
    )
    # 复习记录：用户+复习时间
    op.create_index(
        "idx_review_records_user_date",
        "review_records",
        ["user_id", "reviewed_at"],
    )
    # 题目：科目+活跃状态
    op.create_index(
        "idx_questions_subject_active",
        "questions",
        ["subject", "is_active"],
    )
    # 答题行为：用户+创建时间
    op.create_index(
        "idx_answer_behavior_user_date",
        "answer_behavior",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_answer_behavior_user_date", table_name="answer_behavior")
    op.drop_index("idx_questions_subject_active", table_name="questions")
    op.drop_index("idx_review_records_user_date", table_name="review_records")
    op.drop_index("idx_review_schedules_user_next", table_name="review_schedules")
    op.drop_index("idx_wrong_questions_user_question", table_name="wrong_questions")
    op.drop_index("idx_wrong_questions_user_mastered_date", table_name="wrong_questions")
    op.drop_index("idx_practice_records_user_subject", table_name="practice_records")
    op.drop_index("idx_practice_records_user_date", table_name="practice_records")
