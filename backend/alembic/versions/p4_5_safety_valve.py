"""phase4.5: add experiment safety valve fields

Add fields to recommendation_experiments for:
- max_traffic_percent: limit traffic to experiment
- fallback_strategy_name: strategy to use if experiment fails
- auto_pause_on_error_rate: auto-pause if error rate exceeds threshold
- min_sample_size: minimum samples before auto-pause kicks in
- started_at: when experiment was started
- ended_at: when experiment was ended

Revision ID: p4_5_safety_valve
Revises: g4h5i6j7k8l9
Create Date: 2026-06-28 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p4_5_safety_valve"
down_revision: str | Sequence[str] | None = "g4h5i6j7k8l9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table: str, column: str) -> bool:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def upgrade() -> None:
    if not _has_column("recommendation_experiments", "max_traffic_percent"):
        op.add_column(
            "recommendation_experiments",
            sa.Column("max_traffic_percent", sa.Float(), nullable=False, server_default=sa.text("100.0")),
        )

    if not _has_column("recommendation_experiments", "fallback_strategy_name"):
        op.add_column(
            "recommendation_experiments",
            sa.Column("fallback_strategy_name", sa.String(64), nullable=True),
        )

    if not _has_column("recommendation_experiments", "auto_pause_on_error_rate"):
        op.add_column(
            "recommendation_experiments",
            sa.Column("auto_pause_on_error_rate", sa.Float(), nullable=True),
        )

    if not _has_column("recommendation_experiments", "min_sample_size"):
        op.add_column(
            "recommendation_experiments",
            sa.Column("min_sample_size", sa.Integer(), nullable=False, server_default=sa.text("100")),
        )

    if not _has_column("recommendation_experiments", "started_at"):
        op.add_column(
            "recommendation_experiments",
            sa.Column("started_at", sa.DateTime(), nullable=True),
        )

    if not _has_column("recommendation_experiments", "ended_at"):
        op.add_column(
            "recommendation_experiments",
            sa.Column("ended_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    for col_name in ("ended_at", "started_at", "min_sample_size", "auto_pause_on_error_rate",
                     "fallback_strategy_name", "max_traffic_percent"):
        if _has_column("recommendation_experiments", col_name):
            op.drop_column("recommendation_experiments", col_name)
