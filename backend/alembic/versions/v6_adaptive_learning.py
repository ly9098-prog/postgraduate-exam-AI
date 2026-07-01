"""v6: add adaptive learning tables

V6: 新增 user_adaptive_profile / user_knowledge_adaptive_state /
    user_question_difficulty_state 三张表，支持个性化间隔倍率和题目难度校准。

Revision ID: v6_adaptive_learning
Revises: v5_study_report_idx
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa


revision = "v6_adaptive_learning"
down_revision = "v5_study_report_idx"
branch_labels = None
depends_on = None


def _table_exists(insp, name: str) -> bool:
    return name in insp.get_table_names()


def upgrade():
    insp = sa.inspect(op.get_bind())

    # ── user_adaptive_profile ──
    if not _table_exists(insp, "user_adaptive_profile"):
        op.create_table(
            "user_adaptive_profile",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("interval_factor", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("min_interval_factor", sa.Float(), nullable=False, server_default="0.6"),
            sa.Column("max_interval_factor", sa.Float(), nullable=False, server_default="1.6"),
            sa.Column("target_recall_rate", sa.Float(), nullable=False, server_default="0.8"),
            sa.Column("recent_due_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("recent_due_correct_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_adjusted_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_uap_user_id", "user_adaptive_profile", ["user_id"], unique=True)

    # ── user_knowledge_adaptive_state ──
    if not _table_exists(insp, "user_knowledge_adaptive_state"):
        op.create_table(
            "user_knowledge_adaptive_state",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("knowledge_point_id", sa.Integer(), sa.ForeignKey("knowledge_points.id"), nullable=False),
            sa.Column("interval_factor", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("due_review_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("due_review_correct_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("overdue_wrong_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_adjusted_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_ukas_user_id", "user_knowledge_adaptive_state", ["user_id"])
        op.create_index("ix_ukas_kp_id", "user_knowledge_adaptive_state", ["knowledge_point_id"])

    # ── user_question_difficulty_state ──
    if not _table_exists(insp, "user_question_difficulty_state"):
        op.create_table(
            "user_question_difficulty_state",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id"), nullable=False),
            sa.Column("personal_difficulty_score", sa.Float(), nullable=False, server_default="50"),
            sa.Column("difficulty_label", sa.String(20), nullable=False, server_default="normal"),
            sa.Column("answer_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("wrong_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("avg_answer_time_seconds", sa.Float(), nullable=True),
            sa.Column("fast_correct_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("slow_correct_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("slow_wrong_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("overdue_wrong_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_updated_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_uqds_user_id", "user_question_difficulty_state", ["user_id"])
        op.create_index("ix_uqds_question_id", "user_question_difficulty_state", ["question_id"])

    # ── user_recommend_preference ──
    if not _table_exists(insp, "user_recommend_preference"):
        op.create_table(
            "user_recommend_preference",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("due_weight", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("weakness_weight", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("wrong_weight", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("new_question_weight", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("diversity_weight", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("difficulty_weight", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("path_weight", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("last_adjusted_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )
        op.create_index("ix_urp_user_id", "user_recommend_preference", ["user_id"], unique=True)


def downgrade():
    insp = sa.inspect(op.get_bind())
    if _table_exists(insp, "user_recommend_preference"):
        op.drop_table("user_recommend_preference")
    if _table_exists(insp, "user_question_difficulty_state"):
        op.drop_table("user_question_difficulty_state")
    if _table_exists(insp, "user_knowledge_adaptive_state"):
        op.drop_table("user_knowledge_adaptive_state")
    if _table_exists(insp, "user_adaptive_profile"):
        op.drop_table("user_adaptive_profile")
