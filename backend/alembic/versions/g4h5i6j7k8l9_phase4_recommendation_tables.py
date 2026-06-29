"""phase4: recommendation strategy configs, experiments, assignments, metrics daily

Create 4 new tables for Phase 4 recommendation evaluation:
- recommendation_strategy_configs
- recommendation_experiments
- recommendation_experiment_assignments
- recommendation_metrics_daily

Also add 6 Phase 4 columns to recommendation_logs:
- experiment_id, variant_key, strategy_config_id
- mastery_before, mastery_after, mastery_delta

Revision ID: g4h5i6j7k8l9
Revises: 5edb3d7d7c1f
Create Date: 2026-06-28 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "g4h5i6j7k8l9"
down_revision: str | Sequence[str] | None = "5edb3d7d7c1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    return table in inspector.get_table_names()


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    # ── 1. recommendation_strategy_configs ──
    if not _has_table("recommendation_strategy_configs"):
        op.create_table(
            "recommendation_strategy_configs",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(64), nullable=False),
            sa.Column("display_name", sa.String(128), nullable=False, server_default=""),
            sa.Column("description", sa.String(512), nullable=True),
            sa.Column("scene", sa.String(32), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("weight_vector_similarity", sa.Float(), nullable=False, server_default=sa.text("0.5")),
            sa.Column("weight_knowledge_overlap", sa.Float(), nullable=False, server_default=sa.text("0.2")),
            sa.Column("weight_difficulty_match", sa.Float(), nullable=False, server_default=sa.text("0.1")),
            sa.Column("weight_mastery_gap", sa.Float(), nullable=False, server_default=sa.text("0.1")),
            sa.Column("weight_path_priority", sa.Float(), nullable=False, server_default=sa.text("0.1")),
            sa.Column("exploration_ratio", sa.Float(), nullable=False, server_default=sa.text("0.1")),
            sa.Column("config_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index("ix_recommendation_strategy_configs_name", "recommendation_strategy_configs", ["name"])
        op.create_index("ix_recommendation_strategy_configs_scene", "recommendation_strategy_configs", ["scene"])

    # ── 2. recommendation_experiments ──
    if not _has_table("recommendation_experiments"):
        op.create_table(
            "recommendation_experiments",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("scene", sa.String(32), nullable=False),
            sa.Column("description", sa.String(512), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default=sa.text("'draft'")),
            sa.Column("start_at", sa.DateTime(), nullable=True),
            sa.Column("end_at", sa.DateTime(), nullable=True),
            sa.Column("traffic_ratio", sa.Float(), nullable=False, server_default=sa.text("1.0")),
            sa.Column("variants", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )
        op.create_index("ix_recommendation_experiments_name", "recommendation_experiments", ["name"])
        op.create_index("ix_recommendation_experiments_scene", "recommendation_experiments", ["scene"])

    # ── 3. recommendation_experiment_assignments ──
    if not _has_table("recommendation_experiment_assignments"):
        op.create_table(
            "recommendation_experiment_assignments",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("experiment_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("variant_key", sa.String(16), nullable=False),
            sa.Column("strategy", sa.String(32), nullable=False),
            sa.Column("assigned_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["experiment_id"], ["recommendation_experiments.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("experiment_id", "user_id", name="uq_rea_experiment_user"),
        )
        op.create_index("ix_rea_experiment_id", "recommendation_experiment_assignments", ["experiment_id"])
        op.create_index("ix_rea_user_id", "recommendation_experiment_assignments", ["user_id"])
        op.create_index("ix_rea_variant_key", "recommendation_experiment_assignments", ["variant_key"])
        op.create_index("ix_rea_strategy", "recommendation_experiment_assignments", ["strategy"])

    # ── 4. recommendation_metrics_daily ──
    if not _has_table("recommendation_metrics_daily"):
        op.create_table(
            "recommendation_metrics_daily",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("subject", sa.String(32), nullable=False),
            sa.Column("scene", sa.String(32), nullable=False),
            sa.Column("strategy", sa.String(32), nullable=False),
            sa.Column("variant_key", sa.String(16), nullable=True),
            sa.Column("exposure_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("click_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("answer_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("correct_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("wrong_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("avg_recommend_score", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("avg_similarity", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("avg_mastery_before", sa.Float(), nullable=True),
            sa.Column("avg_mastery_after", sa.Float(), nullable=True),
            sa.Column("avg_mastery_delta", sa.Float(), nullable=True),
            sa.Column("completion_rate", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("accuracy", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("ctr", sa.Float(), nullable=False, server_default=sa.text("0")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "date", "subject", "scene", "strategy", "variant_key",
                name="uq_rmd_date_subject_scene_strategy_variant",
            ),
        )
        op.create_index("ix_rmd_date", "recommendation_metrics_daily", ["date"])
        op.create_index("ix_rmd_subject", "recommendation_metrics_daily", ["subject"])
        op.create_index("ix_rmd_scene", "recommendation_metrics_daily", ["scene"])
        op.create_index("ix_rmd_strategy", "recommendation_metrics_daily", ["strategy"])

    # ── 5. Add Phase 4 columns to recommendation_logs ──
    if _has_table("recommendation_logs"):
        new_columns: dict[str, sa.TypeEngine] = {
            "experiment_id": sa.Integer(),
            "variant_key": sa.String(16),
            "strategy_config_id": sa.Integer(),
            "mastery_before": sa.Float(),
            "mastery_after": sa.Float(),
            "mastery_delta": sa.Float(),
        }
        for col_name, col_type in new_columns.items():
            if not _has_column("recommendation_logs", col_name):
                op.add_column(
                    "recommendation_logs",
                    sa.Column(col_name, col_type, nullable=True),
                )

        # Indexes for new columns
        for col_name in ("experiment_id", "variant_key", "strategy_config_id"):
            idx_name = f"ix_recommendation_logs_{col_name}"
            conn = op.get_bind()
            inspector = sa.inspect(conn)
            existing_indexes = {ix["name"] for ix in inspector.get_indexes("recommendation_logs")}
            if idx_name not in existing_indexes:
                op.create_index(idx_name, "recommendation_logs", [col_name])


def downgrade() -> None:
    # Drop new columns from recommendation_logs
    if _has_table("recommendation_logs"):
        for col_name in ("mastery_delta", "mastery_after", "mastery_before",
                         "strategy_config_id", "variant_key", "experiment_id"):
            if _has_column("recommendation_logs", col_name):
                op.drop_column("recommendation_logs", col_name)

    # Drop tables in reverse order
    for table_name in (
        "recommendation_metrics_daily",
        "recommendation_experiment_assignments",
        "recommendation_experiments",
        "recommendation_strategy_configs",
    ):
        if _has_table(table_name):
            op.drop_table(table_name)
