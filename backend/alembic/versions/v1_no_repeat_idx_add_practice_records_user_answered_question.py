"""add practice_records user_answered_question index

V1: 为 practice_records 表新增覆盖索引，加速"查询用户最近 N 天做过的题目"子查询。
索引列: (user_id, answered_at, question_id)

Revision ID: v1_no_repeat_idx
Revises: 3a30ad6482fa
Create Date: 2026-07-01
"""
import sqlalchemy as sa

from alembic import op

revision = "v1_no_repeat_idx"
down_revision = "3a30ad6482fa"
branch_labels = None
depends_on = None


def upgrade():
    # 幂等检查：索引是否已存在
    insp = sa.inspect(op.get_bind())
    existing_indexes = [idx["name"] for idx in insp.get_indexes("practice_records")]
    if "idx_practice_records_user_answered_question" in existing_indexes:
        return

    op.create_index(
        "idx_practice_records_user_answered_question",
        "practice_records",
        ["user_id", "answered_at", "question_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "idx_practice_records_user_answered_question",
        table_name="practice_records",
    )
