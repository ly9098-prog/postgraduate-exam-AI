"""v3: add mastery fields to user_knowledge_states

V3: 补齐 confidence、recent_* 系列、last_is_correct、last_answer_time_seconds。
同时为 mastery_score 新增复合索引 (user_id, mastery_score) 加速薄弱知识点查询。

Revision ID: v3_mastery_fields
Revises: v2_user_question_state
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "v3_mastery_fields"
down_revision = "v2_user_question_state"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    existing_cols = [col["name"] for col in insp.get_columns("user_knowledge_states")]

    # 幂等添加列
    if "confidence" not in existing_cols:
        op.add_column("user_knowledge_states", sa.Column("confidence", sa.Float(), nullable=False, server_default="0"))
    if "recent_answer_count" not in existing_cols:
        op.add_column("user_knowledge_states", sa.Column("recent_answer_count", sa.Integer(), nullable=False, server_default="0"))
    if "recent_correct_count" not in existing_cols:
        op.add_column("user_knowledge_states", sa.Column("recent_correct_count", sa.Integer(), nullable=False, server_default="0"))
    if "recent_wrong_count" not in existing_cols:
        op.add_column("user_knowledge_states", sa.Column("recent_wrong_count", sa.Integer(), nullable=False, server_default="0"))
    if "last_is_correct" not in existing_cols:
        op.add_column("user_knowledge_states", sa.Column("last_is_correct", sa.Boolean(), nullable=True))
    if "last_answer_time_seconds" not in existing_cols:
        op.add_column("user_knowledge_states", sa.Column("last_answer_time_seconds", sa.Integer(), nullable=True))

    # 新增索引
    existing_indexes = [idx["name"] for idx in insp.get_indexes("user_knowledge_states")]
    if "idx_uks_user_mastery" not in existing_indexes:
        op.create_index("idx_uks_user_mastery", "user_knowledge_states", ["user_id", "mastery_score"], unique=False)


def downgrade():
    op.drop_index("idx_uks_user_mastery", table_name="user_knowledge_states")
    op.drop_column("user_knowledge_states", "last_answer_time_seconds")
    op.drop_column("user_knowledge_states", "last_is_correct")
    op.drop_column("user_knowledge_states", "recent_wrong_count")
    op.drop_column("user_knowledge_states", "recent_correct_count")
    op.drop_column("user_knowledge_states", "recent_answer_count")
    op.drop_column("user_knowledge_states", "confidence")
