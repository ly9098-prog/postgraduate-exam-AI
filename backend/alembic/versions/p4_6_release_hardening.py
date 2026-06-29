"""phase4.6: create missing tables and add composite indexes

Create 5 tables that were previously only created via Base.metadata.create_all
in init_db() (which is a no-op in production):
- knowledge_points
- question_knowledge_points
- knowledge_edges
- user_knowledge_states
- recommendation_logs

Also add composite indexes to recommendation_logs for:
- (user_id, scene, created_at) — recommendation engine hot path
- (user_id, request_id) — feedback matching
- (created_at) — metrics aggregation time range scans

Revision ID: p4_6_release_hardening
Revises: p4_5_safety_valve
Create Date: 2026-06-28 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "p4_6_release_hardening"
down_revision: str | Sequence[str] | None = "p4_5_safety_valve"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return table in inspector.get_table_names()


def _has_index(table: str, index: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if not _has_table(table):
        return False
    existing = {ix["name"] for ix in inspector.get_indexes(table)}
    return index in existing


def upgrade() -> None:
    # ── 1. knowledge_points ──
    if not _has_table("knowledge_points"):
        op.create_table(
            "knowledge_points",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("subject", sa.String(32), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("normalized_name", sa.String(128), nullable=False),
            sa.Column("aliases", sa.JSON(), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("difficulty_level", sa.SmallInteger(), server_default=sa.text("3")),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("subject", "normalized_name", name="uq_kp_subject_normalized_name"),
        )
        op.create_index("ix_knowledge_points_subject", "knowledge_points", ["subject"])
        op.create_index("ix_knowledge_points_name", "knowledge_points", ["name"])
        op.create_index("ix_knowledge_points_normalized_name", "knowledge_points", ["normalized_name"])

    # ── 2. question_knowledge_points ──
    if not _has_table("question_knowledge_points"):
        op.create_table(
            "question_knowledge_points",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("question_id", sa.Integer(), nullable=False),
            sa.Column("knowledge_point_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(16), server_default=sa.text("'main'")),
            sa.Column("weight", sa.Float(), server_default=sa.text("1.0")),
            sa.Column("source", sa.String(16), server_default=sa.text("'imported'")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["question_id"], ["questions.id"]),
            sa.ForeignKeyConstraint(["knowledge_point_id"], ["knowledge_points.id"]),
            sa.UniqueConstraint("question_id", "knowledge_point_id", name="uq_qkp_question_kp"),
        )
        op.create_index("ix_qkp_question_id", "question_knowledge_points", ["question_id"])
        op.create_index("ix_qkp_knowledge_point_id", "question_knowledge_points", ["knowledge_point_id"])

    # ── 3. knowledge_edges ──
    if not _has_table("knowledge_edges"):
        op.create_table(
            "knowledge_edges",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("subject", sa.String(32), nullable=False),
            sa.Column("source_knowledge_point_id", sa.Integer(), nullable=False),
            sa.Column("target_knowledge_point_id", sa.Integer(), nullable=False),
            sa.Column("relation_type", sa.String(16), nullable=False),
            sa.Column("weight", sa.Float(), nullable=False, server_default=sa.text("1.0")),
            sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
            sa.Column("source", sa.String(16), nullable=False, server_default=sa.text("'manual'")),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(
                ["source_knowledge_point_id"], ["knowledge_points.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["target_knowledge_point_id"], ["knowledge_points.id"], ondelete="CASCADE"
            ),
            sa.UniqueConstraint(
                "source_knowledge_point_id", "target_knowledge_point_id", "relation_type",
                name="uq_ke_source_target_relation",
            ),
        )
        op.create_index("ix_knowledge_edges_subject", "knowledge_edges", ["subject"])
        op.create_index("ix_knowledge_edges_source_kp", "knowledge_edges", ["source_knowledge_point_id"])
        op.create_index("ix_knowledge_edges_target_kp", "knowledge_edges", ["target_knowledge_point_id"])
        op.create_index("ix_knowledge_edges_relation_type", "knowledge_edges", ["relation_type"])
        op.create_index("ix_ke_subject_relation", "knowledge_edges", ["subject", "relation_type"])

    # ── 4. user_knowledge_states ──
    if not _has_table("user_knowledge_states"):
        op.create_table(
            "user_knowledge_states",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("subject", sa.String(32), nullable=False),
            sa.Column("knowledge_point_id", sa.Integer(), nullable=False),
            sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0")),
            sa.Column("correct_count", sa.Integer(), server_default=sa.text("0")),
            sa.Column("wrong_count", sa.Integer(), server_default=sa.text("0")),
            sa.Column("accuracy", sa.Float(), server_default=sa.text("0.0")),
            sa.Column("mastery_score", sa.Float(), server_default=sa.text("0.0")),
            sa.Column("weakness_level", sa.String(16), server_default=sa.text("'unknown'")),
            sa.Column("last_practiced_at", sa.DateTime(), nullable=True),
            sa.Column("last_wrong_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["knowledge_point_id"], ["knowledge_points.id"]),
            sa.UniqueConstraint("user_id", "knowledge_point_id", name="uq_uks_user_kp"),
        )
        op.create_index("ix_uks_user_id", "user_knowledge_states", ["user_id"])
        op.create_index("ix_uks_subject", "user_knowledge_states", ["subject"])
        op.create_index("ix_uks_knowledge_point_id", "user_knowledge_states", ["knowledge_point_id"])
        op.create_index("ix_uks_user_subject", "user_knowledge_states", ["user_id", "subject"])

    # ── 5. recommendation_logs ──
    if not _has_table("recommendation_logs"):
        op.create_table(
            "recommendation_logs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("question_id", sa.Integer(), nullable=False),
            sa.Column("subject", sa.String(32), nullable=False),
            sa.Column("scene", sa.String(32), nullable=False),
            sa.Column("strategy", sa.String(32), nullable=False),
            sa.Column("source_question_id", sa.Integer(), nullable=True),
            sa.Column("recommend_score", sa.Float(), nullable=True),
            sa.Column("similarity", sa.Float(), nullable=True),
            sa.Column("reason", sa.String(256), nullable=True),
            sa.Column("request_id", sa.String(64), nullable=True),
            sa.Column("experiment_id", sa.Integer(), nullable=True),
            sa.Column("variant_key", sa.String(16), nullable=True),
            sa.Column("strategy_config_id", sa.Integer(), nullable=True),
            sa.Column("mastery_before", sa.Float(), nullable=True),
            sa.Column("mastery_after", sa.Float(), nullable=True),
            sa.Column("mastery_delta", sa.Float(), nullable=True),
            sa.Column("shown_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("clicked_at", sa.DateTime(), nullable=True),
            sa.Column("answered_at", sa.DateTime(), nullable=True),
            sa.Column("is_correct", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["question_id"], ["questions.id"]),
        )
        op.create_index("ix_recommendation_logs_user_id", "recommendation_logs", ["user_id"])
        op.create_index("ix_recommendation_logs_question_id", "recommendation_logs", ["question_id"])
        op.create_index("ix_recommendation_logs_subject", "recommendation_logs", ["subject"])
        op.create_index("ix_recommendation_logs_scene", "recommendation_logs", ["scene"])
        op.create_index("ix_recommendation_logs_strategy", "recommendation_logs", ["strategy"])
        op.create_index("ix_recommendation_logs_request_id", "recommendation_logs", ["request_id"])
        op.create_index("ix_recommendation_logs_experiment_id", "recommendation_logs", ["experiment_id"])
        op.create_index("ix_recommendation_logs_variant_key", "recommendation_logs", ["variant_key"])
        op.create_index("ix_recommendation_logs_strategy_config_id", "recommendation_logs", ["strategy_config_id"])

    # ── 6. Add composite indexes to recommendation_logs ──
    if _has_table("recommendation_logs"):
        if not _has_index("recommendation_logs", "ix_rl_user_scene_created"):
            op.create_index(
                "ix_rl_user_scene_created",
                "recommendation_logs",
                ["user_id", "scene", "created_at"],
            )
        if not _has_index("recommendation_logs", "ix_rl_user_request"):
            op.create_index(
                "ix_rl_user_request",
                "recommendation_logs",
                ["user_id", "request_id"],
            )
        if not _has_index("recommendation_logs", "ix_rl_created_at"):
            op.create_index(
                "ix_rl_created_at",
                "recommendation_logs",
                ["created_at"],
            )


def downgrade() -> None:
    # Drop composite indexes from recommendation_logs
    if _has_table("recommendation_logs"):
        for idx in ("ix_rl_created_at", "ix_rl_user_request", "ix_rl_user_scene_created"):
            if _has_index("recommendation_logs", idx):
                op.drop_index(idx, table_name="recommendation_logs")

    # Drop tables in reverse order
    for table_name in (
        "recommendation_logs",
        "user_knowledge_states",
        "knowledge_edges",
        "question_knowledge_points",
        "knowledge_points",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
