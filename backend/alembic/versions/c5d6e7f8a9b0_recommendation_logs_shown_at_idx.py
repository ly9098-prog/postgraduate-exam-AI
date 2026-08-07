"""recommendation_logs: add shown_at indexes for daily aggregation.

recommendation_metrics_service.aggregate_recommendation_metrics_daily filters
on shown_at (range) and groups by (subject_id, scene, strategy) — previously a
full table scan. Add a single-column index on shown_at and a composite serving
the WHERE/GROUP BY.

Revision ID: c5d6e7f8a9b0
Revises: b2c3d4e5f6a7
Create Date: 2026-08-07
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names()


def _has_index(table: str, index: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return index in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    if not _has_table("recommendation_logs"):
        return

    if not _has_index("recommendation_logs", "ix_rl_shown_at"):
        op.create_index(
            "ix_rl_shown_at", "recommendation_logs", ["shown_at"],
        )
    if not _has_index("recommendation_logs", "ix_rl_shown_at_subject_scene_strategy"):
        op.create_index(
            "ix_rl_shown_at_subject_scene_strategy",
            "recommendation_logs",
            ["shown_at", "subject_id", "scene", "strategy"],
        )


def downgrade() -> None:
    if not _has_table("recommendation_logs"):
        return

    if _has_index("recommendation_logs", "ix_rl_shown_at_subject_scene_strategy"):
        op.drop_index(
            "ix_rl_shown_at_subject_scene_strategy", table_name="recommendation_logs",
        )
    if _has_index("recommendation_logs", "ix_rl_shown_at"):
        op.drop_index("ix_rl_shown_at", table_name="recommendation_logs")
