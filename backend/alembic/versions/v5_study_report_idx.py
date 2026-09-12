"""v5: add study report indexes

V5: 为学习报告统计查询添加性能索引。

Revision ID: v5_study_report_idx
Revises: v3_mastery_fields
Create Date: 2026-07-01
"""
import sqlalchemy as sa

from alembic import op

revision = "v5_study_report_idx"
down_revision = "v3_mastery_fields"
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())

    # practice_records(user_id, question_id) — 用于错题统计 join
    existing = [idx["name"] for idx in insp.get_indexes("practice_records")]
    if "idx_pr_user_question" not in existing:
        op.create_index(
            "idx_pr_user_question",
            "practice_records",
            ["user_id", "question_id"],
            unique=False,
        )

    # user_question_state(user_id, box_level) — 用于 Leitner 分布
    existing = [idx["name"] for idx in insp.get_indexes("user_question_state")]
    if "idx_uqs_user_box" not in existing:
        op.create_index(
            "idx_uqs_user_box",
            "user_question_state",
            ["user_id", "box_level"],
            unique=False,
        )

    # user_knowledge_states(user_id, mastery_score, confidence) — 用于知识点分类
    existing = [idx["name"] for idx in insp.get_indexes("user_knowledge_states")]
    if "idx_uks_user_mastery_conf" not in existing:
        op.create_index(
            "idx_uks_user_mastery_conf",
            "user_knowledge_states",
            ["user_id", "mastery_score", "confidence"],
            unique=False,
        )


def downgrade():
    insp = sa.inspect(op.get_bind())
    for tbl, idx in [
        ("user_knowledge_states", "idx_uks_user_mastery_conf"),
        ("user_question_state", "idx_uqs_user_box"),
        ("practice_records", "idx_pr_user_question"),
    ]:
        existing = [i["name"] for i in insp.get_indexes(tbl)]
        if idx in existing:
            op.drop_index(idx, table_name=tbl)
